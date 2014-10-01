import numpy as np

from . import core, util
from . import lowlevel as ll


def eigh(A, lower=True, overwrite_a=True, eigvals=None):
    """Compute the eigen-decomposition of a symmetric/hermitian matrix.

    Use Scalapack to compute the eigenvalues and eigenvectors of a
    distributed matrix.

    Parameters
    ----------
    A : DistributedMatrix
        The matrix to decompose.
    lower : boolean, optional
        Scalapack uses only half of the matrix, by default the lower
        triangle will be used. Set to False to use the upper triangle.
    overwrite_a : boolean, optional
        By default the input matrix is destroyed, if set to False a
        copy is taken and operated on.
    eigvals : tuple (lo, hi), optional
        Indices of the lowest and highest eigenvalues you would like to
        calculate. Indexed from zero.

    Returns
    -------
    evals : np.ndarray
        The eigenvalues of the matrix, they are returned as a global
        numpy array of all values.
    evecs : DistributedMatrix
        The eigenvectors as a DistributedMatrix.
    """

    # Check if matrix is square
    util.assert_square(A)

    A = A if overwrite_a else A.copy()

    task = 'V'
    erange = 'A'
    uplo = "L" if lower else "U"
    N = A.global_shape[0]
    low, high = 1, 1

    # Get eigval indices if set
    if eigvals is not None:
        low = eigvals[0] + 1
        high = eigvals[1] + 1
        erange = 'I'

    evecs = core.DistributedMatrix.empty_like(A)
    evals = np.empty(N, dtype=util.real_equiv(A.dtype))

    args = [task, erange, uplo, N, A, 1.0, 1.0, low, high, evals, evecs]

    call_table = {'S': (ll.pssyevr, args + [ll.WorkArray('S', 'I')]),
                  'D': (ll.pdsyevr, args + [ll.WorkArray('D', 'I')]),
                  'C': (ll.pcheevr, args + [ll.WorkArray('C', 'S', 'I')]),
                  'Z': (ll.pzheevr, args + [ll.WorkArray('Z', 'D', 'I')])}

    func, args = call_table[A.sc_dtype]
    info, m, nz = func(*args)

    if info < 0:
        raise Exception("Failure.")

    return evals, evecs


def cholesky(A, lower=False, overwrite_a=False, zero_triangle=True):
    """Compute the Cholesky decomposition of a symmetric/hermitian matrix.

    Parameters
    ----------
    A : DistributedMatrix
        The matrix to decompose.
    lower : boolean, optional
        Compute the upper or lower Cholesky factor. Additionally Scalapack
        will only touch the upper or lower triangle of A.
    overwrite_a : boolean, optional
        By default the input matrix is destroyed, if set to False a
        copy is taken and operated on.
    zero_triangle : boolean, optional
        By default Scalapack ignores the other triangle, if set, we explicitly
        zero it.

    Returns
    -------
    cholesky : DistributedMatrix
        The Cholesky factor as a DistributedMatrix.
    """

    # Check if matrix is square
    util.assert_square(A)

    A = A if overwrite_a else A.copy()

    uplo = "L" if lower else "U"
    N = A.global_shape[0]

    args = [uplo, N, A]

    call_table = {'S': (ll.pspotrf, args),
                  'D': (ll.pdpotrf, args),
                  'C': (ll.pcpotrf, args),
                  'Z': (ll.pzpotrf, args)}

    func, args = call_table[A.sc_dtype]
    info = func(*args)

    if info < 0:
        raise core.ScalapackException("Failure.")

    ## Zero other triangle
    # by default scalapack doesn't touch the other triangle
    # (determined by upper arg). We explicitly zero it here.
    if zero_triangle:
        ri, ci = A.indices()

        # Create a mask of the other triangle
        mask = (ci <= ri) if lower else (ci >= ri)
        A.local_array[:] = A.local_array * mask

    return A


def dot(A, B, transA='N', transB='N'):
    """Parallel matrix multiplication.

    Parameters
    ----------
    A, B : DistributedMatrix
        Matrices to multiply.
    transA, transB : ['N', 'T', 'H', 'C']
        Whether we should use a transpose, rather than A or B themselves.
        Either, do nothing ('N'), normal transpose ('T'), Hermitian transpose
        ('H'), or complex conjugation only ('C').

    Returns
    -------
    C : DistributedMatrix
    """

    if transA not in ['N', 'T', 'H', 'C']:
        raise core.ScalapyException("Trans argument for matrix A invalid")
    if transB not in ['N', 'T', 'H', 'C']:
        raise core.ScalapyException("Trans argument for matrix B invalid")
    if A.dtype != B.dtype:
        raise core.ScalapyException("Matrices must have same type")
    # Probably should validate context too

    m = A.global_shape[0] if transA in ['N', 'C'] else A.global_shape[1]
    n = B.global_shape[1] if transB in ['N', 'C'] else B.global_shape[0]
    k = A.global_shape[1] if transA in ['N', 'C'] else A.global_shape[0]
    l = B.global_shape[0] if transB in ['N', 'C'] else B.global_shape[1]

    if l != k:
        raise core.ScalapyException("Matrix shapes are incompatible.")

    C = core.DistributedMatrix([m, n], dtype=A.dtype, block_shape=A.block_shape, context=A.context)

    args = [transA, transB, m, n, k, 1.0, A, B, 0.0, C]

    call_table = { 'S' : (ll.psgemm, args),
                   'C' : (ll.pcgemm, args),
                   'D' : (ll.pdgemm, args),
                   'Z' : (ll.pzgemm, args) }


    func, args = call_table[A.sc_dtype]
    func(*args)

    return C