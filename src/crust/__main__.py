# -*- coding: utf-8 -*-
"""
Entry point for ``python -m crust [survey.yaml]``

Opens the desktop GUI through `crust.gui.__main__.main`, on the survey config
given as the optional argument.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from crust.gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
