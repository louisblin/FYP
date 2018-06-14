import argparse
import sys

from page_rank.model.tools.simulation import PageRankSimulation

RUN_TIME = 2.1


def run(show_in=False, show_out=False):
    ############################################################################
    # Construct simulation graph
    # From: https://www.youtube.com/watch?v=P8Kt6Abq_rM

    edges = [
        ('A', 'B'),
        ('A', 'C'),
        ('B', 'D'),
        ('C', 'A'),
        ('C', 'B'),
        ('C', 'D'),
        ('D', 'C'),
    ]

    ############################################################################
    # Run simulation / report

    with PageRankSimulation(RUN_TIME, edges, damping=1-10e-10,
                            pause=not show_out) as sim:
        sim.draw_input_graph(show_graph=show_in)
        sim.run(verify=True)
        sim.draw_output_graph(show_graph=show_out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Simple Page Rank graph with 4 vertices.')
    parser.add_argument('--show-in', action='store_true',
                        help='Display directed graph input.')
    parser.add_argument('--show-out', action='store_true',
                        help='Display ranks curves output.')

    sys.exit(run(**vars(parser.parse_args())))
