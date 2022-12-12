#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

import logging
import sys
from typing import List, Set

from ci_connector_ops import utils

RELEASE_STAGE_TO_STRICTNESS_LEVEL_MAPPING = {"generally_available": "high"}
BACKWARD_COMPATIBILITY_REVIEWERS = {"connector-operations", "connector-extensibility"}
TEST_STRICTNESS_LEVEL_REVIEWERS = {"connector-operations"}
GA_CONNECTOR_REVIEWERS = {"gl-python"}

def find_connectors_with_bad_strictness_level() -> List[str]:
    """Check if changed connectors have the expected SAT test strictness level according to their release stage.
    1. Identify changed connectors
    2. Retrieve their release stage from the catalog
    3. Parse their acceptance test config file
    4. Check if the test strictness level matches the strictness level expected for their release stage.

    Returns:
        List[str]: List of changed connector names that are not matching test strictness level expectations.
    """
    connectors_with_bad_strictness_level = []
    changed_connector_names = utils.get_changed_connector_names()
    for connector_name in changed_connector_names:
        connector_release_stage = utils.get_connector_release_stage(connector_name)
        expected_test_strictness_level = RELEASE_STAGE_TO_STRICTNESS_LEVEL_MAPPING.get(connector_release_stage)
        _, acceptance_test_config = utils.get_acceptance_test_config(connector_name)
        can_check_strictness_level = all(
            [item is not None for item in [connector_release_stage, expected_test_strictness_level, acceptance_test_config]]
        )
        if can_check_strictness_level:
            try:
                assert acceptance_test_config.get("test_strictness_level") == expected_test_strictness_level
            except AssertionError:
                connectors_with_bad_strictness_level.append(connector_name)
    return connectors_with_bad_strictness_level

def find_changed_ga_connectors() -> List[str]:
    """Find GA connectors modified on the current branch.

    Returns:
        List[str]: The list of GA connector that were modified on the current branch.
    """
    changed_connector_names = utils.get_changed_connector_names()
    return [connector_name for connector_name in changed_connector_names if utils.get_connector_release_stage(connector_name) == "generally_available"]

def find_mandatory_reviewers() -> Set[str]:
    mandatory_reviewers = set()
    ga_connector_changes = find_changed_ga_connectors()
    backward_compatibility_changes = utils.get_changed_acceptance_test_config(diff_regex="disable_for_version")
    test_strictness_level_changes = utils.get_changed_acceptance_test_config(diff_regex="test_strictness_level")
    if ga_connector_changes:
        mandatory_reviewers.update(GA_CONNECTOR_REVIEWERS)
    if backward_compatibility_changes:
        mandatory_reviewers.update(BACKWARD_COMPATIBILITY_REVIEWERS)
    if  test_strictness_level_changes:
        mandatory_reviewers .update(TEST_STRICTNESS_LEVEL_REVIEWERS)
    return mandatory_reviewers

def check_test_strictness_level():
    connectors_with_bad_strictness_level = find_connectors_with_bad_strictness_level()
    if connectors_with_bad_strictness_level:
        logging.error(
            f"The following GA connectors must enable high test strictness level: {connectors_with_bad_strictness_level}. Please check this documentation for details: https://docs.airbyte.com/connector-development/testing-connectors/source-acceptance-tests-reference/#strictness-level"
        )
        sys.exit(1)
    else:
        sys.exit(0)

def print_mandatory_reviewers() -> bool:
    mandatory_reviewers = find_mandatory_reviewers()
    if mandatory_reviewers:
        print(f"MANDATORY_REVIEWERS={','.join(mandatory_reviewers)}")
    else:
        print('MANDATORY_REVIEWERS=""')


