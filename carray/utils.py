########################################################################
#
#       License: BSD
#       Created: August 5, 2010
#       Author:  Francesc Alted - faltet@pytables.org
#
#       $Id: utils.py 4463 2010-06-04 15:17:09Z faltet $
#
########################################################################

"""Utility functions.

"""

import sys, os, os.path, subprocess, math
import itertools as it
from time import time, clock
import numpy as np
import carray as ca


def show_stats(explain, tref):
    "Show the used memory (only works for Linux 2.6.x)."
    # Build the command to obtain memory info
    cmd = "cat /proc/%s/status" % os.getpid()
    sout = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout
    for line in sout:
        if line.startswith("VmSize:"):
            vmsize = int(line.split()[1])
        elif line.startswith("VmRSS:"):
            vmrss = int(line.split()[1])
        elif line.startswith("VmData:"):
            vmdata = int(line.split()[1])
        elif line.startswith("VmStk:"):
            vmstk = int(line.split()[1])
        elif line.startswith("VmExe:"):
            vmexe = int(line.split()[1])
        elif line.startswith("VmLib:"):
            vmlib = int(line.split()[1])
    sout.close()
    print "Memory usage: ******* %s *******" % explain
    print "VmSize: %7s kB\tVmRSS: %7s kB" % (vmsize, vmrss)
    print "VmData: %7s kB\tVmStk: %7s kB" % (vmdata, vmstk)
    print "VmExe:  %7s kB\tVmLib: %7s kB" % (vmexe, vmlib)
    tnow = time()
    print "WallClock time:", round(tnow - tref, 3)
    return tnow


def detect_number_of_cores():
    """Detect the number of cores on a system."""
    # Linux, Unix and MacOS:
    if hasattr(os, "sysconf"):
        if os.sysconf_names.has_key("SC_NPROCESSORS_ONLN"):
            # Linux & Unix:
            ncpus = os.sysconf("SC_NPROCESSORS_ONLN")
            if isinstance(ncpus, int) and ncpus > 0:
                return ncpus
        else: # OSX:
            return int(os.popen2("sysctl -n hw.ncpu")[1].read())
    # Windows:
    if os.environ.has_key("NUMBER_OF_PROCESSORS"):
        ncpus = int(os.environ["NUMBER_OF_PROCESSORS"]);
        if ncpus > 0:
            return ncpus
    return 1 # Default


def set_num_threads(nthreads):
    """Set the number of threads to be used during carray operation.

    This affects to both Blosc and Numexpr (if available).  If you want
    to change this number only for Blosc, use `blosc_set_number_threads`
    instead.
    """
    ca.blosc_set_num_threads(nthreads)
    if ca.numexpr_here:
        ca.numexpr.set_num_threads(nthreads)


##### Code for computing optimum chunksize follows  #####

def csformula(expectedsizeinMB):
    """Return the fitted chunksize for expectedsizeinMB."""
    # For a basesize of 1 KB, this will return:
    # 4 KB for datasets <= .1 KB
    # 64 KB for datasets == 1 MB
    # 1 MB for datasets >= 10 GB
    basesize = 1024
    return basesize * int(2**(math.log10(expectedsizeinMB)+6))


def limit_es(expectedsizeinMB):
    """Protection against creating too small or too large chunks."""
    if expectedsizeinMB < 1e-4:     # < .1 KB
        expectedsizeinMB = 1e-4
    elif expectedsizeinMB > 1e4:    # > 10 GB
        expectedsizeinMB = 1e4
    return expectedsizeinMB


def calc_chunksize(expectedsizeinMB):
    """Compute the optimum chunksize for memory I/O in carray/ctable.

    carray stores the data in chunks and there is an optimal length for
    this chunk for compression purposes (it is around 1 MB for modern
    processors).  However, due to the implementation, carray logic needs
    to always reserve all this space in-memory.  Booking 1 MB is not a
    drawback for large carrays (>> 1 MB), but for smaller ones this is
    too much overhead.

    The tuning of the chunksize parameter affects the performance and
    the memory consumed.  This is based on my own experiments and, as
    always, your mileage may vary.
    """

    expectedsizeinMB = limit_es(expectedsizeinMB)
    zone = int(math.log10(expectedsizeinMB))
    expectedsizeinMB = 10**zone
    chunksize = csformula(expectedsizeinMB)
    return chunksize


def fromiter(iterator, dtype, count=-1, **kwargs):
    """Create a carray/ctable from `iterator` object.

    `dtype` specifies the type of the outcome object.

    `count` specifies the number of items to read from iterable. The
    default is -1, which means all data is read.

    You can pass whatever additional arguments supported by
    carray/ctable constructors in `kwargs`.
    """

    if count == -1:
        # Try to guess the size of the iterator length
        if hasattr(iterator, "__length_hint__"):
            count = iterator.__length_hint__()
        else:
            # No guess
            count = sys.maxint

    # First, create the container
    obj = ca.carray(np.array([], dtype=dtype), **kwargs)
    chunksize = obj.chunksize
    nread, bsize = 0, 0
    while nread < count:
        if count == sys.maxint:
            bsize = -1
        elif nread + chunksize > count:
            bsize = count - nread
        else:
            bsize = chunksize
        chunkiter = it.islice(iterator, bsize)
        chunk = np.fromiter(chunkiter, dtype=dtype, count=bsize)
        obj.append(chunk)
        nread += len(chunk)
        # Check the end of the iterator
        if len(chunk) < chunksize:
            break
    return obj


class cparms(object):
    """Class to host parameters for compression and other filters.

    You can pass the `clevel` and `shuffle` params to the constructor.
    If you do not pass them, the defaults are ``5`` and ``True``
    respectively.

    It offers these read-only attributes::

      * clevel: the compression level

      * shuffle: whether the shuffle filter is active or not

    """

    @property
    def clevel(self):
        """The compression level."""
        return self._clevel

    @property
    def shuffle(self):
        """Shuffle filter is active?"""
        return self._shuffle

    def __init__(self, clevel=5, shuffle=True):
        """Create an instance with `clevel` and `shuffle` params."""
        if not isinstance(clevel, int):
            raise ValueError, "`clevel` must an int."
        if not isinstance(shuffle, (bool, int)):
            raise ValueError, "`shuffle` must a boolean."
        shuffle = bool(shuffle)
        if clevel < 0:
            raiseValueError, "clevel must be a positive integer"
        self._clevel = clevel
        self._shuffle = shuffle

    def __repr__(self):
        args = ["clevel=%d"%self._clevel, "shuffle=%s"%self._shuffle]
        return '%s(%s)' % (self.__class__.__name__, ', '.join(args))


def get_len_of_range(start, stop, step):
    """Get the length of a (start, stop, step) range."""
    n = 0
    if start < stop:
        n = ((stop - start - 1) // step + 1);
    return n




# Main part
# =========
if __name__ == '__main__':
    _test()


## Local Variables:
## mode: python
## py-indent-offset: 4
## tab-width: 4
## fill-column: 72
## End:
