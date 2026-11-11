#!/bin/bash
# Bygger image lokalt och deployar till k3s på <deploy-host>.
#
# Image:n byggs med podman på den här datorn och strömmas via ssh till DEPLOY_HOST,
# där den importeras i k3s containerd (namespace k8s.io). kubectl körs lokalt och
# pratar med <deploy-host>s kluster via kubeconfig.
#
# Miljövariabler:
#   DEPLOY_HOST   ssh-värd med k3s (standard: <deploy-host>). Sätt till "local" om k3s
#                 körs på den här datorn.
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-local}"
VERSION="v24.6-$(date +%s)"
IMAGE_NAME="localhost/aktieanalys:$VERSION"

echo "1. Validerar kod..."
python3 -m py_compile app.py src/api/routes.py src/core/*.py

echo "2. Bygger image $IMAGE_NAME..."
podman build --no-cache -t "$IMAGE_NAME" -f Containerfile .

echo "3. Strömmar image till k3s på $DEPLOY_HOST (namespace k8s.io)..."
# Strömmas direkt utan mellanfil, så ingen förutsägbar temp-fil på målet kan bytas ut
# innan den importeras som root.
if [ "$DEPLOY_HOST" = "local" ]; then
  podman save "$IMAGE_NAME" | sudo k3s ctr -n k8s.io images import -
else
  podman save "$IMAGE_NAME" | ssh "$DEPLOY_HOST" "sudo k3s ctr -n k8s.io images import -"
fi

echo "4. Uppdaterar YAML och tvingar omstart..."
sed -i "s|image: localhost/aktieanalys:.*|image: $IMAGE_NAME|g" aktieanalys.yaml
kubectl apply -f aktieanalys.yaml
kubectl delete pod -l app=aktieanalys
kubectl rollout status deploy/aktieanalys --timeout=180s

echo "KLART! Verifiera att rubriken visar $VERSION"
echo "Kom ihåg att committa aktieanalys.yaml (ny image-tagg)."
