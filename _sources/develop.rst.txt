##################################
Contributing to Morelia 👷‍♀️
##################################

So, you want to contribute to Morelia? Well, this is the place to be! 

=========================================================
Setting Up a Morelia Development Enviornment 🧑‍🏭
=========================================================

The first step to setting up a Morelia development enviornment is
to follow the "Setting Up Your Enviornment" section on the
:doc:`getting started page </getting_started>`.

After that, clone an up to date copy of the `source code repository <https://github.com/Pinnacle-Technology-Inc/Morelia>`_.

----------------------------------------------------------
Constructing a Python Environment with Anaconda 🧑‍🍳
----------------------------------------------------------
If you do not want to use Anaconda to install the project dependencies,
``pip`` will automatically install them when we install Morelia
for development.
Therefore, this step is technically optional, but **highly recommended**.
Anaconda is a fantastic tool for managing Python environments
and makes setting one up for Morelia a breeze.

To get started, begin by installing Anaconda (or Miniconda) if
you do not already have it. Download the installer `here <https://www.anaconda.com/download>`_.

After Anaconda is installed, running the following command
in the top level directory of your cloned repo
downloads and sets up all the dependencies for Morelia.

.. code-block::

   conda env create -f environment.yml

--------------------------------------
Installing Morelia for Development 🚜
--------------------------------------
After you have cloned the source code (and hopefully set up and Anaconda environment, but again, that step is not strictly required),
the last step is to install Morelia itself for development! Currently, the way to do this is using ``pip`` to creat an **editable install**.
This allows us to Morelia as if it is a package installed in our environment, but the package will automatically update as we make
changes to the source code. Therefore, **there is no need to reinstall Morelia each time**.

To create this editable install, run the following in the top level of your repository:

.. code-block::

   pip install -e .

=================
Running Tests 🧪
=================

Building out tests for Morelia is an ongoing effort, but is done using the `pytest <https://docs.pytest.org/en/stable/>`_ framework.
The current tests for Morelia can be found in the ``tests`` directory. To run the tests, use the following command from the top-level
of your repository

.. code-block::

   pytest

It is worth noting there is also an ``old_tests`` folder. These scripts from a deprecated testing framework that require physical devices to 
be plugged into your computer. Currently, these are still in the repository as they can be useful for in-house testing of devices or testing
some older functionality that do not yet have pytest tests written. The future of these files is uncertain, but for now they are there so
it's probably useful to know what they are.

==========================
Building Documentation 📜
==========================

Morelia's documentation is built using `Spinx <https://www.sphinx-doc.org/en/master/index.html>`_,
and the source files can be found in the ``docs`` folder. It also uses the `autodoc <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html>`_ and `sphinx-autodoc-typehints <https://github.com/tox-dev/sphinx-autodoc-typehints>`_ extensions to automatically build documenatation for all functions and classes using docstrings. 
To build the ``HTML`` documentation, simply run

.. code-block::
   
        make html

in the `docs` folder. There is no need to commit ``HTML`` documentation to GitHub, as it is
automatically built via a continuous integration (CI) pipeline when a branch is merged into ``integration``.

Sphinx offers a bunch of other formats to output documentation in! Fell free to explore, however we only
use ``HTML`` for public facing docs.

=========================
Uploading to PyPI 📦
=========================

Morelia is on the Python Package Index! New versions are automatically packaged an uploaded by a GitHub Actions CI pipeline within the repo that runs
*every time a new tag is pushed*. In order to make sure that the run succeeds, **make sure that the version of the tag you pushed matches
the version number in the pyproject.toml file.** If these versions do not match, the run will likely fail. Specifically,
if the version number is not updated, it will try to upload a version to PyPI that is already present, causing things to implode.
Note that if you are not a maintainer,
you will not have permissions to push a tag to GitHub.
