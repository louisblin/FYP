import errno
import logging
import os
import signal
import site
import sys
from contextlib import contextmanager
from functools import wraps

from page_rank.model.tools.fixed_point import FXfamily

ITER_BITS = 2  # see c_models/src/neuron/messages/in_messages.h
LOG_IMPORTANT = (logging.INFO + logging.WARNING) // 2


class PageRankNoConvergence(RuntimeError):
    pass


class FailedOnWarningError(RuntimeError):
    pass


class GUITimeoutError(Exception):
    pass


#
# Utility functions
#


_fp_builder = FXfamily(n_bits=32)


def to_fp(n):
    return _fp_builder(n)


def to_hex(fp):
    return fp.toBinaryString(logBase=4, twosComp=False)


def getLogger(name=__name__, log_level=logging.INFO):
    logger = logging.getLogger(name)

    # Log level
    logger.setLevel(log_level)

    # Already exists - attaching multiple times a handler duplicates messages.
    if logger.handlers:
        return logger

    # Log formatting
    fmt = '%(asctime)s %(levelname)s: %(message)s'
    fmt_date = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt, fmt_date)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # New 'IMPORTANT' level

    logging.addLevelName(LOG_IMPORTANT, "IMPORTANT")

    def important(self, message, *args, **kwargs):
        if self.isEnabledFor(LOG_IMPORTANT):
            # Yes, logger takes its '*args' as 'args'.
            self._log(LOG_IMPORTANT, message, args, **kwargs)

    logging.Logger.important = important

    return logger


@contextmanager
def silence_output(enable=True, pipe_to=os.devnull):
    """Conditionally silences the outputs of stdout and stderr

    :param enable: if False, will disable silencing (i.e. normally output)
    :param pipe_to: the file to which captured outputs will be piped to.
    """
    def _no_op():
        yield

    def _silencer():
        new_target = open(pipe_to, "w")
        old_stdout, sys.stdout = sys.stdout, new_target
        old_stderr, sys.stderr = sys.stderr, new_target
        try:
            yield new_target  # Execute user code
        finally:
            new_target.flush()
            new_target.close()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    return _silencer() if enable else _no_op()


def install_requirements(requirements_file=None):
    """Installs the requirements.txt file in the parent directory

    This is usefull when running on the HBP platform, that does not provide a
    standard to install additional dependencies.

    :param requirements_file: absolute path to the requirements.txt
    """
    if requirements_file is None:
        requirements_file = os.path.realpath(
            os.path.join(os.path.dirname(__file__), '../requirements.txt'))

    os.system('pip install --user -r "{}"'.format(requirements_file))
    reload(site)


def gui_timeout(seconds=10, error_message=os.strerror(errno.ETIME)):
    """Times out a the GUI matplotlib application after `seconds` sec.
    """

    def decorator(func):
        def _handle_timeout(signum, frame):
            raise GUITimeoutError(
                "Displaying graph timed out after {}sec. This is probably due "
                "to an invalid value of 'DISPLAY={}'...".format(
                    seconds, os.getenv('DISPLAY')))

        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result

        return wraps(func)(wrapper)

    return decorator


def graph_visualiser(func):
    """Handle the basic logic around graph outputting
    """

    def decorator(*args, **kwargs):
        """
        :param show_graph: whether to display the graph, default is False
        """
        import matplotlib.pyplot as plt

        show_graph = kwargs.pop('show_graph', False)

        @gui_timeout(1)
        def gui_clear():
            # Freezes with TkAgg backend and invalid DISPLAY value
            # TODO: move in a thread that is killed
            plt.clf()  # Clear plot

        @gui_timeout(60 if show_graph else 5)
        def gui_run():
            try:
                gui_clear()
            except GUITimeoutError:
                getLogger().warning("Skip frozen pyplt.clf()...")

            func(*args, **kwargs)

            if show_graph:
                plt.show()

        gui_run()

    return decorator


def extract_router_provenance(collect_names=None):
    from spinn_front_end_common.utilities import globals_variables
    from spinn_front_end_common.interface.interface_functions \
        import RouterProvenanceGatherer

    if collect_names is None:
        collect_names = [
            'total_multi_cast_sent_packets',
            'total_created_packets',
            'total_dropped_packets',
            'total_missed_dropped_packets',
            'total_lost_dropped_packets'
        ]

    m = globals_variables.get_simulator()

    router_provenance = RouterProvenanceGatherer()
    router_prov = router_provenance(m._txrx, m._machine, m._router_tables, True)

    res = dict().fromkeys(collect_names, 0)
    for item in router_prov:
        getLogger().debug('{} => {}'.format(item.names, item.value))
        name = item.names[-1]
        if name in collect_names:
            res[name] += int(item.value)

    return res


def node_formatter(name):
    return "Node %s" % name


def float_formatter(number):
    from page_rank.model.tools.simulation import FLOAT_PRECISION

    return ("%.{}f".format(FLOAT_PRECISION)) % number


def format_ranks_string(labels, ranks, diff_only=False, diff_max=50):
    """Pretty prints a table of ranks values

    :param ranks: dict of name-indexed rows of values, or list of a single
                  row of values
    :return: None
    """
    from prettytable import PrettyTable
    from page_rank.model.tools.simulation import TOL

    if diff_only and len(ranks) == 2:
        # Filter out valid ranks
        [(lbl1, row_1), (lbl2, row_2)] = ranks.items()
        diff_idx = [i for i, (r1, r2) in enumerate(zip(row_1, row_2))
                    if abs(r1 - r2) >= TOL]
        labels = [labels[i] for i in diff_idx]
        row_1 = [row_1[i] for i in diff_idx]
        row_2 = [row_2[i] for i in diff_idx]
        if len(diff_idx) > diff_max:
            compacted_label = "{}..{}".format(labels[diff_max], labels[-1])
            labels = labels[:diff_max] + [compacted_label]
            row_1 = row_1[:diff_max] + [0]
            row_2 = row_2[:diff_max] + [0]

        # Construct table
        table = PrettyTable([''] + map(node_formatter, labels))
        table.add_row([lbl1] + map(float_formatter, row_1))
        table.add_row([lbl2] + map(float_formatter, row_2))
    else:
        # Multiple rows, indexed by row name
        table = PrettyTable([''] + map(node_formatter, labels))
        for name, row in ranks.items():
            table.add_row([name] + map(float_formatter, row))

    return table.get_string()


def compute_page_rank(g, labels, d, d_sum, tol, max_iter=100):
    """Return the PageRank of the nodes in the graph.

    Adapted to:
     - use binary fixed-point arithmetic operations, like SpiNNaker
     - return the # of iterations required to compute the Page Rank

    Source
    ------
    networkx/algorithms/link_analysis/pagerank_alg.py


    :param g: input graph
    :param labels: labels of the nodes
    :param d: damping factor
    :param d_sum: damping sum
    :param tol: convergence tolerance
    :param max_iter: max iteration count before giving up on convergence
    :return: ( <dict> node-indexed dict of ranks, <int> # iterations required )
    """
    import networkx as nx
    import numpy as np

    w = nx.stochastic_graph(g, weight=None)
    n = w.number_of_nodes()

    # Init fixed-point constants
    d = to_fp(d)
    tol = to_fp(tol)
    zero = to_fp(0)
    one = to_fp(1.)
    n = to_fp(n)
    d_sum = to_fp(d_sum)

    # Iterate up to max_iter iterations
    x = dict.fromkeys(w, one / n)
    for iter_no in range(max_iter):
        getLogger().debug('\n===== TIME STEP = {} ====='.format(iter_no))
        x_last = x
        x = dict.fromkeys(x_last.keys(), zero)

        for node in x:
            pkt = x_last[node] / to_fp(len(w[node]))
            getLogger().debug('[t=%04d|#%3s] Sending pkt %f[%s]' % (
                iter_no, node, pkt, to_hex(pkt)))

            # Exchange ranks
            for conn_node in w[node]:  # edge: node -> conn_node
                prev = x[conn_node]
                # Simulates payload-lossy encoding of the iteration
                # See c_models/src/neuron/in_messages.h
                #   function: in_messages_payload_format
                x[conn_node] += ((pkt >> ITER_BITS) << ITER_BITS)
                getLogger().debug("[idx=%3s] %f[%s] + %f[%s] = %f[%s]" % (
                    conn_node, prev, to_hex(prev), pkt,
                    to_hex(pkt), x[conn_node],
                    to_hex(x[conn_node])))

        # Compute dangling factor
        if d != one:
            for node in x:
                prev = x[node]
                x[node] = d_sum + d * x[node]
                getLogger().debug(
                    "[idx=%3s] %f[%s] * %f[%s] + %f[%s] = %f[%s]" % (
                        node, d, to_hex(d), prev, to_hex(prev),
                        d_sum,
                        to_hex(d_sum), x[node],
                        to_hex(x[node])))

        # Check convergence, l1 norm
        err = sum([abs(x[node] - x_last[node]) for node in x])
        if err < n * tol:
            if labels:
                x = np.array([np.float64(x[v]) for v in labels])
            return x, iter_no + 1  # iter t+1 happens at the end of time t

    raise PageRankNoConvergence(max_iter)