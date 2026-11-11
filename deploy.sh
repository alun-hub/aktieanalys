#!/bin/bash
# Bygger image lokalt och deployar till k3s på <deploy-host>.
#
# Image:n byggs med podman på den här datorn, kopieras med scp till DEPLOY_HOST
# och importeras i k3s containerd (namespace k8s.io) där. kubectl körs lokalt och
# pratar med <deploy-host>s kluster via kubeconfig.
#
# Miljövariabler:
#   DEPLOY_HOST   ssh-värd med k3s (standard: <deploy-host>). Sätt till "local" om k3s
#                 körs på den här datorn.
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-local}"
VERSION="v24.6-$(date +%s)"
IMAGE_NAME="localhost/aktieanalys:$VERSION"
TAR="portal.tar"
REMOTE_TAR="/tmp/aktieanalys-$VERSION.tar"

cleanup() {
  rm -f "$TAR"
  if [ "$DEPLOY_HOST" != "local" ]; then
    ssh -o BatchMode=yes "$DEPLOY_HOST" "rm -f '$REMOTE_TAR'" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "1. Validerar kod..."
python3 -m py_compile app.py src/api/routes.py src/core/*.py

echo "2. Bygger image $IMAGE_NAME..."
podman build --no-cache -t "$IMAGE_NAME" -f Containerfile .

echo "3. Exporterar image och importerar till k3s på $DEPLOY_HOST (namespace k8s.io)..."
rm -f "$TAR"   # podman save vägrar skriva över en befintlig fil
podman save "$IMAGE_NAME" -o "$TAR"
if [ "$DEPLOY_HOST" = "local" ]; then
  sudo k3s ctr -n k8s.io images import "$TAR"
else
  scp -q "$TAR" "$DEPLOY_HOST:$REMOTE_TAR"
  ssh "$DEPLOY_HOST" "sudo k3s ctr -n k8s.io images import '$REMOTE_TAR'"
fi

echo "4. Uppdaterar YAML och tvingar omstart..."
sed -i "s|image: localhost/aktieanalys:.*|image: $IMAGE_NAME|g" aktieanalys.yaml
kubectl apply -f aktieanalys.yaml
kubectl delete pod -l app=aktieanalys
kubectl rollout status deploy/aktieanalys --timeout=180s

echo "KLART! Verifiera att rubriken visar $VERSION"
echo "Kom ihåg att committa aktieanalys.yaml (ny image-tagg)."
