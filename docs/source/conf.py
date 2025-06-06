# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

#Configuration for the autodoc extension.
#See for more details: https://sphinx-rtd-tutorial.readthedocs.io/en/latest/sphinx-config.html#autodoc-configuration
import os
import sys
sys.path.insert(0, os.path.abspath('../../src/Morelia'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Morelia'
copyright = '2024, Pinnacle Technology'
author = 'Pinnacle Technology'
release = 'v1.6.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.duration',
   'sphinx.ext.autosummary',
    'sphinx.ext.autodoc',
    'sphinx.ext.githubpages',
    'sphinx_autodoc_typehints'
]

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_logo = '_static/logo.png'
html_css_files = [ 'style.css' ]
