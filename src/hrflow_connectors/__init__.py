from hrflow_connectors.connectors.salesforce.connector import Salesforce
from hrflow_connectors.connectors.smartrecruiters import SmartRecruiters
from hrflow_connectors.connectors.talentsoft import TalentSoft
from hrflow_connectors.core.connector import hrflow_connectors_manifest  # noqa
from hrflow_connectors.core.documentation import generate_docs  # noqa

__version__ = "2.0.0"
__CONNECTORS__ = [SmartRecruiters, TalentSoft, Salesforce]

# This makes sure that connector are in module namespace
# and that the automatic workflow code generation should work
for connector in __CONNECTORS__:
    globals()[connector.model.name] = connector
