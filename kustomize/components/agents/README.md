# Agents Component

Adds the `agents` microservice to Online Boutique.

## Features
- Deployment, Service, ServiceAccount
- Injects `AGENTS_SERVICE_ADDR` into `frontend` via a patch
- References `GOOGLE_API_KEY` from Kubernetes Secret `agents-api-key`

## Usage
Uncomment/add in root `kustomize/kustomization.yaml`:
```yaml
components:
  - components/agents
```

Create / override the secret value (recommended do NOT commit real key):
```bash
kubectl create secret generic agents-api-key \
  --from-literal=GOOGLE_API_KEY=YOUR_KEY -n default --dry-run=client -o yaml | kubectl apply -f -
```

If using registry/tag rewrite components, include them after this component.
