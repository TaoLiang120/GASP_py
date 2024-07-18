# coding: utf-8
# Copyright (c) Henniggroup.
# Distributed under the terms of the MIT License.

from __future__ import division, unicode_literals, print_function

"""
Run module:

This module is run to do a genetic algorithm structure search.

Usage: python run.py /path/to/gasp/input/file

"""

import os

import gasp.process.preprocess as mypre
import gasp.process.process as mypro
import gasp.process.postprocess as mypost


def main():
    THIS_PATH = os.getcwd()
    objects_dict, garun_dir, data_writer, log_writer, thisRestart = mypre.preprocess(THIS_PATH)
    mypro.process(objects_dict, garun_dir, data_writer, log_writer, thisRestart, THIS_PATH)
    mypost.postprocess(objects_dict, garun_dir, data_writer, log_writer, THIS_PATH)


if __name__ == "__main__":
    main()
