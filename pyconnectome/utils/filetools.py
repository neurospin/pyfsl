##########################################################################
# NSAP - Copyright (C) CEA, 2013
# Distributed under the terms of the CeCILL-B license, as published by
# the CEA-CNRS-INRIA. Refer to the LICENSE file or to
# http://www.cecill.info/licences/Licence_CeCILL-B_V1-en.html
# for details.
##########################################################################

"""
File utilities.
"""

# System import
import os
import glob
import subprocess
import tempfile
import shutil

# Package import
from pyconnectome import DEFAULT_FSL_PATH
from pyconnectome.wrapper import FSLWrapper

# Third party
import numpy
import nibabel
import vtk
from vtk.util.numpy_support import vtk_to_numpy


def convert_connectomist_trk_fibers_to_tck(dwi, trk_tractogram, tck_tractogram,
                                           tempdir=None):
    """
    Convert a TRK tractogram generated by Connectmist to a TCK tractogram
    (MRtrix format).
    The input tractogram is assumed to be in LAS convention.

    Parameters
    ----------
    dwi: str
        Path to dwi (or nodif_brain) to specify diffusion space.
    trk_tractogram: str
        Path to the input Connectomist TRK tractogram.
    tck_tractogram: str
        Path to the output TCK tractogram. Extension .tck is added if
        not present.
    tempdir: str, default None
        A temporary directory to store intermediate tractogram.
    """
    # Local import
    import tractconverter

    # Check existence of input file
    for path in (dwi, trk_tractogram):
        if not os.path.isfile(path):
            raise ValueError("File does not exist: %s" % path)

    # Create a temporary directory to store an intermediate tractogram
    tempdir = tempfile.mkdtemp(prefix="tractconverter_", dir=tempdir)

    # Change orientation: LAS -> LPI
    trk = nibabel.streamlines.load(trk_tractogram)
    trk.header["voxel_order"] = "LPI"
    tmp_trk_tractogram = os.path.join(tempdir, "tmp.trk")
    trk.save(tmp_trk_tractogram)

    # Add .tck extension to output path if not the case
    if not tck_tractogram.endswith(".tck"):
        tck_tractogram += ".tck"

    # Convert TRK to TCK using tractconverter
    trk_fibers = tractconverter.TRK(tmp_trk_tractogram)
    tck_fibers = tractconverter.TCK.create(tck_tractogram, hdr=trk_fibers.hdr,
                                           anatFile=dwi)
    tractconverter.convert(trk_fibers, tck_fibers)

    # Clean temporary directory
    shutil.rmtree(tempdir)

    return tck_tractogram


def convert_mitk_vtk_fibers_to_tck(vtk_tractogram, tck_tractogram):
    """
    Convert a .fib tractogram (VTK polydata format) generated by MITK to
    a .tck (MRtrix TCK format) tractogram.
    The input tractogram is assumed to be in LPS convention.

    Parameters
    ----------
    vtk_tractogram: str
        Path to the input .fib tractogram (VTK polydata format).
    tck_tractogram: str
        Path to the output TCK tractogram. Extension .tck is added if
        not present.
    """
    # Check existence of input file
    if not os.path.isfile(vtk_tractogram):
        raise ValueError("File does not exist: %s" % vtk_tractogram)

    # Read the input data with VTK
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(vtk_tractogram)
    reader.Update()
    polydata = reader.GetOutput()

    # List of fibers = list of point arrays
    fibers = []
    nb_fibers = polydata.GetNumberOfCells()

    # For each fiber
    for i in range(nb_fibers):
        # Get the points of the fiber
        vtk_pts = polydata.GetCell(i).GetPoints().GetData()
        # Convert the coordinates into a numpy array
        fiber_pts = vtk_to_numpy(vtk_pts)
        # Create a copy of the array (vtk seems to keep a pointer and
        # overrides the previous result at the next call)
        fiber_pts_copy = numpy.array(fiber_pts)
        fibers.append(fiber_pts_copy)

    # LPS to RAS matrix: MITK (like ITK) uses the LPS convention.
    # TCK requires RAS
    lps_to_ras = numpy.diag([-1, -1, 1, 1])

    # Create a Nibabel tractogram
    tractogram = nibabel.streamlines.Tractogram(streamlines=fibers,
                                                affine_to_rasmm=lps_to_ras)

    # Create the TCK file with Nibabel
    if not tck_tractogram.endswith(".tck"):
        tck_tractogram += ".tck"
    nibabel.streamlines.TckFile(tractogram=tractogram).save(tck_tractogram)

    return tck_tractogram


def mrtrix_extract_b0s_and_mean_b0(dwi, b0s, mean_b0, nb_threads=1):
    """ Extract b=0 (bvalue=0) volumes from DWI and compute mean b=0 volume.

    Parameters
    ----------
    dwi: str
        The diffusion file.
    b0s: str
        The b0 volumes file.
    mean_b0:
        The mean b0 volumes file.
    nb_threads: int, default None
        Number of threads that MRtrix is allowed to use.
    """
    # Extract the b0 volumes
    cmd_1 = ["dwiextract", "-bzero", dwi, b0s,
             "-nthreads", "%i" % nb_threads, "-failonwarn"]
    subprocess.check_call(cmd_1)

    # Average the b0 volumes
    cmd_2 = ["mrmath", b0s, "mean", mean_b0, "-axis", "3",
             "-nthreads", "%i" % nb_threads, "-failonwarn"]
    subprocess.check_call(cmd_2)


def extract_image(in_file, index, out_file=None):
    """ Extract the image at 'index' position.

    Parameters
    ----------
    in_file: str (mandatory)
        the input image.
    index: int (mandatory)
        the index of last image dimention to extract.
    out_file: str (optional, default None)
        the name of the extracted image file.

    Returns
    -------
    out_file: str
        the name of the extracted image file.
    """
    # Set default output if necessary
    dirname = os.path.dirname(in_file)
    basename = os.path.basename(in_file).split(".")[0]
    if out_file is None:
        out_file = os.path.join(
            dirname, "extract{0}_{1}.nii.gz".format(index, basename))

    # Extract the image of interest
    image = nibabel.load(in_file)
    affine = image.get_affine()
    extracted_array = image.get_data()[..., index]
    extracted_image = nibabel.Nifti1Image(extracted_array, affine)
    nibabel.save(extracted_image, out_file)

    return out_file


def fslreorient2std(input_image, output_image, fslconfig=DEFAULT_FSL_PATH):
    """ Reorient an image to match the approximate orientation of the standard
    template image (MNI152).

    It only applies 0, 90, 180 or 270 degree rotations.
    It is not a registration tool.
    It requires NIfTI images with valid orientation information in them (seen
    by valid labels in FSLView). This tool assumes the labels are correct - if
    not, fix that before using this. If the output name is not specified the
    equivalent transformation matrix is written to the standard output.

    The basic usage is:
        fslreorient2std <input_image> [output_image]

    Parameters
    ----------
    input_image: str (mandatory)
        The image to reorient.
    output_image: str (mandatory)
        The reoriented image.
    fslconfig: str (optional, default DEFAULT_FSL_PATH)
        The FSL configuration batch.
    """
    # check the input parameter
    if not os.path.isfile(input_image):
        raise ValueError("'{0}' is not a valid input file.".format(
                         input_image))

    # Define the FSL command
    cmd = ["fslreorient2std", input_image, output_image]

    # Call fslreorient2std
    fslprocess = FSLWrapper(cmd, shfile=fslconfig)
    fslprocess()

    return glob.glob(output_image + "*")[0]


def apply_mask(input_file, output_fileroot, mask_file,
               fslconfig=DEFAULT_FSL_PATH):
    """ Apply a mask to an image.

    Parameters
    ----------
    input_file: str (mandatory)
        The image to mask.
    output_fileroot: str (mandatory)
        The masked image root name.
    mask_file: str (mandatory)
        The mask image.
    fslconfig: str (optional, default DEFAULT_FSL_PATH)
        The FSL configuration batch.

    Returns
    -------
    mask_file: str
        the masked input image.
    """
    # check the input parameter
    for filename in (input_file, mask_file):
        if not os.path.isfile(filename):
            raise ValueError("'{0}' is not a valid input "
                             "file.".format(filename))

    # Define the FSL command
    # "-mas": use (following image>0) to mask current image.
    cmd = ["fslmaths", input_file, "-mas", mask_file, output_fileroot]

    # Call fslmaths
    fslprocess = FSLWrapper(cmd, shfile=fslconfig)
    fslprocess()

    return glob.glob(output_fileroot + ".*")[0]
