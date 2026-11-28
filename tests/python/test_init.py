# SPDX-License-Identifier: LGPL-2.1-or-later

import inspect
from collections.abc import Iterable
from importlib.metadata import version

import rexlib_metadata
from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import ConventionBundle


def test_the_version_is_the_installed_distributions():
	assert rexlib_metadata.__version__ == version("rexlib-metadata")


def test_the_public_signature_resolves_at_runtime():
	signature = inspect.signature(rexlib_metadata.read, eval_str=True)

	assert signature.parameters["bundle"].annotation == (
		ConventionBundle | Iterable[ConventionBundle] | None
	)
	assert signature.parameters["reader"].annotation == Reader | None
