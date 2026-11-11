#!/bin/bash
# Bygger image lokalt och deployar till ett k3s-kluster.
#
# Image:n byggs med podman, strömmas via ssh till DEPLOY_HOST och importeras i k3s
# containerd (namespace k8s.io). kubectl körs lokalt mot klustret via kubeconfig.
#
# Konfiguration (miljövariabler, eller i en lokal deploy.env som är gitignorerad):
#   DEPLOY_HOST    ssh-värd som kör k3s, eller "local" om k3s körs på den här datorn.
#   INGRESS_HOSTS  kommaseparerade värdnamn för ingressen, t.ex. "aktieanalys.example.com".
#
# Se deploy.env.example.
set -euo pipefail

cd "$(dirname "$0")"
[ -f deploy.env ] && . ./deploy.env

: "${DEPLOY_HOST:?Sätt DEPLOY_HOST (ssh-värd eller 'local') – se deploy.env.example}"
: "${INGRESS_HOSTS:?Sätt INGRESS_HOSTS (kommaseparerade värdnamn) – se deploy.env.example}"

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

echo "4. Applicerar manifest och väntar på utrullning..."
# Image-taggen sätts i flykten – den spårade aktieanalys.yaml ändras inte.
sed "s|image: localhost/aktieanalys:.*|image: $IMAGE_NAME|" aktieanalys.yaml | kubectl apply -f -

{
  cat <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aktieanalys
spec:
  rules:
YAML
  IFS=',' read -ra HOSTS <<< "$INGRESS_HOSTS"
  for h in "${HOSTS[@]}"; do
    h="${h// /}"
    [ -n "$h" ] || continue
    cat <<YAML
  - host: $h
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: aktieanalys
            port:
              number: 80
YAML
  done
} | kubectl apply -f -

kubectl rollout status deploy/aktieanalys --timeout=180s

echo "KLART! Verifiera att rubriken visar $VERSION"
