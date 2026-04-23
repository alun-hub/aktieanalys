#!/bin/bash
set -e

# Hårdkodad version för att undvika fel
VERSION="v17.5"
IMAGE_NAME="localhost/aktieanalys:$VERSION"

echo "1. Validerar kod..."
python3 -m py_compile app.py src/api/routes.py src/core/strategy.py

echo "2. Bygger image $IMAGE_NAME..."
podman build --no-cache -t $IMAGE_NAME -f Containerfile .

echo "3. Exporterar och importerar till k3s (namespace k8s.io)..."
podman save $IMAGE_NAME -o portal.tar
sudo k3s ctr -n k8s.io images remove $IMAGE_NAME || true
sudo k3s ctr -n k8s.io images import portal.tar
rm portal.tar

echo "4. Uppdaterar YAML och tvingar omstart..."
sed -i "s|image: localhost/aktieanalys:.*|image: $IMAGE_NAME|g" aktieanalys.yaml
kubectl apply -f aktieanalys.yaml
kubectl delete pod -l app=aktieanalys

echo "KLART! Verifiera att rubriken visar $VERSION"
