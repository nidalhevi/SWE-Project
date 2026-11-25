"""Join the existing full integration runner; core-only tests also run separately."""
from tests_stage67.test_requests_core import RequestTests
from tests_stage67.test_preferences_core import PreferenceTests
from tests_stage67.test_bridge_core import WorkerBridgeTests
from tests_stage67.test_workflow_qt import ClientOptionTests, WorkflowTests, RefereeWorkflowTests
