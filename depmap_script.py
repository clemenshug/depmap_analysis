import csv
import argparse as ap
import logging
from math import ceil, log10
import pandas as pd
import depmap_network_functions as dnf
from indra.tools.assemble_corpus import dump_statements
from indra.tools.assemble_corpus import load_statements as ac_load_stmts
from time import time
import pdb

# Temp fix because indra doesn't import when script is run from terminal
import sys
sys.path.append('~/repos/indra/')

logger = logging.getLogger('SlowClap')

# 1. no geneset -> use corr from full DepMap data, no filtering needed
# 2. geneset, not strict -> interaction has to contain at least one gene from
#    the loaded list
# 3. geneset loaded, strict -> each correlation can only contain genes from
#    the loaded data set


def read_gene_set_file(gf, data):
    gset = []
    with open(gf, 'rt') as f:
        for g in f.readlines():
            gn = g.upper().strip()
            if gn in data:
                gset.append(gn)
    return gset


def main(args):

    # Open data file
    data = pd.read_csv(args.ceres_file, index_col=0, header=0)
    data = data.T

    if args.geneset_file:
        # Read gene set to look at
        gene_filter_list = read_gene_set_file(gf=args.geneset_file, data=data)

    # 1. no loaded gene list OR 2. loaded gene list but not strict -> data.corr
    if not args.geneset_file or (args.geneset_file and not args.strict):
        # Calculate the full correlations, or load from cached
        if args.recalc:
            corr = data.corr()
            corr.to_hdf('correlations.h5', 'correlations')
        else:
            corr = pd.read_hdf(args.corr_file, 'correlations')
        # No gene set file, leave 'corr' intact and unstack
        if not args.geneset_file:
            fcorr_list = corr.unstack()

        # Gene set file present: filter and unstack
        elif args.geneset_file and not args.strict:
            fcorr_list = corr[gene_filter_list].unstack()

    # 3. Strict: both genes in interaction must be from loaded set
    elif args.geneset_file and args.strict:
        fcorr_list = data[gene_filter_list].corr().unstack()

    # Remove self correlation, correlations below ll, sort on magnitude,
    # leave correlation intact
    flarge_corr = fcorr_list[fcorr_list != 1.0]
    flarge_corr = flarge_corr[flarge_corr.abs() > args.ll]
    if args.ul < 1.0:
        flarge_corr = flarge_corr[flarge_corr.abs() < args.ul]
    fsort_corrs = flarge_corr[
        flarge_corr.abs().sort_values(ascending=False).index]

    # Find out if the HGNC pairs are connected and if they are how
    all_hgnc_ids = set()
    uniq_pairs = set()
    with open(args.outbasename+'_all.csv', 'w', newline='') as csvf:
        wrtr = csv.writer(csvf, delimiter=',')
        for pair in fsort_corrs.items():
            (id1, id2), correlation = pair
            if frozenset([id1, id2, correlation]) not in uniq_pairs:
                uniq_pairs.add(frozenset([id1, id2, correlation]))
                all_hgnc_ids.update([id1, id2])
                wrtr.writerow([id1, id2, correlation])

    # Get statements from file or from database that contain any gene from
    # provided list as set
    if args.statements_in:  # Get statments from file
        stmts_all = set(ac_load_stmts(args.statements_in))
    else:  # Use api to get statements. NOT the same as querying for each ID
        if args.geneset_file:
            stmts_all = dnf.load_statements(gene_filter_list)
        else:
            # if there is no gene set file, restrict to gene ids in
            # correlation data
            stmts_all = dnf.load_statements(list(all_hgnc_ids))

    # Dump statements to pickle file if output name has been given
    if args.statements_out:
        dump_statements(stmts=stmts_all, fname=args.statements_out)

    # Loop through the unique pairs
    dir_conn_pairs = []
    unexplained = []
    counter = 0
    npairs = len(uniq_pairs)
    for pair in uniq_pairs:
        counter +=1
        if counter % max(10, (10**ceil(log10(npairs)))//100) == 0:
            logger.info('Pair %i or %i' % (counter, npairs))
        pl = list(pair)
        for li in pl:
            if type(li) == float:
                correlation = li
                break
        pl.remove(correlation)
        id1, id2 = pl
        if dnf.are_connected(id1, id2, long_stmts=stmts_all):
            logger.info('Found connection between %s and %s ')
            dir_conn_pairs.append([id1, id2, correlation,
                                   dnf.connection_types(id1, id2,
                                                        long_stmts=stmts_all)])
        else:
            unexplained.append([id1, id2, correlation])

    with open(args.outbasename+'_connections.csv', 'w', newline='') as csvf:
        wrtr = csv.writer(csvf, delimiter=',')
        wrtr.writerows(dir_conn_pairs)

    with open(args.outbasename+'_unexplained.csv', 'w', newline='') as csvf:
        wrtr = csv.writer(csvf, delimiter=',')
        wrtr.writerows(unexplained)


if __name__ == '__main__':
    parser = ap.ArgumentParser()
    parser.add_argument('-c', '--corr-file', required=True,
                        help='Precalculated correlations in h5 format')
    parser.add_argument('-f', '--ceres-file', required=True,
                        help='Ceres correlation score in csv format')
    parser.add_argument('-g', '--geneset-file',
                        help='Filter to interactions with gene set data file.')
    parser.add_argument('-o', '--outbasename', default=str(int(time())),
                        help='Base name for outfiles. Default: UTC timestamp')
    parser.add_argument('-r', '--recalc', action='store_true',
                        help='With \'-r\', recalculate full gene-gene '
                             'correlation of data set.')
    parser.add_argument('-s', '--strict', action='store_true',
                        help='With \'-s\', the correlations are restricted to '
                             'only be between loaded gene set. If no gene set '
                             'is loaded, this option has no effect.')
    parser.add_argument('-sti', '--statements-in', help='Loads a pickle file '
                                                        'to use instead of '
                                                        'quering a database.')
    parser.add_argument('-sto', '--statements-out', help='Saves the used '
                                                         'statements read from '
                                                         'the database')
    parser.add_argument('-ll', type=float, default=0.5,
                        help='Lower limit CERES correlation score filter.')
    parser.add_argument('-ul', type=float, default=1.0,
                        help='Upper limit CERES correlation score filter.')

    a = parser.parse_args()
    main(a)
