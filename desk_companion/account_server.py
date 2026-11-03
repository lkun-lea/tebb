"""Desktop entry; packaged sitecustomize may already have frozen the account."""
from .account_bootstrap import launch
from .runtime_instance import InstanceInUse, INSTANCE_EXIT_CODE
from .personalization_cloud import CloudError

if __name__=='__main__':
    try:
        launch()
    except InstanceInUse as exc:
        print(str(exc),flush=True)
        raise SystemExit(INSTANCE_EXIT_CODE)
    except CloudError as exc:
        print(str(exc),flush=True)
        raise SystemExit(74)
