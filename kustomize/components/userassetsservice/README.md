# User Assets Service Component

Adds the `userassetsservice` microservice (user-uploaded asset storage) to Online Boutique.

## Features
- Deployment, Service, ServiceAccount
- Injects `USER_ASSETS_SERVICE_ADDR` into `frontend`
- Ephemeral storage via `emptyDir` (adjust to PVC in production)

## Usage
In root `kustomize/kustomization.yaml`:
```yaml
components:
  - components/userassetsservice
```

Optional tuning via env vars defined in manifest:
- `UAS_MAX_UPLOAD_MB`
- `UAS_MAX_ASSETS_PER_USER`
- `UAS_ALLOWED_MIME`

Add persistent storage (example patch overlay):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: userassetsservice
spec:
  template:
    spec:
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: userassets-pvc
```
