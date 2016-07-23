# -*- coding: utf-8 -*-
"""This module contains blueprint for API v1."""


from __future__ import absolute_import
from __future__ import unicode_literals

import flask

from cephlcm.api.views.v1 import auth


BLUEPRINT_NAME = "ApiV1"
"""Blueprint name for the API v1."""

BLUEPRINT = flask.Blueprint(BLUEPRINT_NAME, __name__)
"""Blueprint."""

auth.AuthView.register_to(BLUEPRINT)