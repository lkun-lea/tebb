"""Compare configuration identities without persisting credentials or endpoint URLs."""
from desk_companion.observability.tool_monitor import fingerprint


def model_configuration(mode,model_id=''):
    from desk_companion.evaluation.agent_evals import CONTRACT_VERSION
    if mode=='fixture':return dict(id='eval-fixture',model='eval-fixture',version=fingerprint(dict(mode='fixture',contract=CONTRACT_VERSION)))
    from desk_companion.models import model_catalog,model_network
    item=model_catalog.require_item(model_id)if model_id else model_catalog.require_active()
    from desk_companion.evaluation.profile_snapshot import selected_policies
    value=dict(item=item,network=model_network.effective_policy(item.get('network_mode', 'inherit')),policies=selected_policies([item]))
    return dict(id=item['id'],model=item['model'],version=fingerprint(value))
