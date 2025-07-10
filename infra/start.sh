#!/bin/bash
sed -i 's/\r$//' start.sh

# Install Morelia from Morelia-develop branch (will have to change PATH later)
echo "Installing Morelia..."
cd .. 
pip install . 
cd infra

# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# update and install software to verify HashiCorp's GPG signature
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common

# Install HashiCorp GPG key
wget -O- https://apt.releases.hashicorp.com/gpg | \
gpg --dearmor | \
sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null

# verify key
gpg --no-default-keyring \
--keyring /usr/share/keyrings/hashicorp-archive-keyring.gpg \
--fingerprint

# Add official HashiCorp repository to system
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list

# update the package again for the addition of new packages
sudo apt-get update

# Install both docker and terraform
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo apt-get install terraform

touch terraform.tfvars
cp "default-values.txt" "terraform.tfvars"

sudo terraform init
sudo terraform refresh
sudo terraform destroy -auto-approve
sudo terraform apply -auto-approve

echo "Grafana server started on http://localhost:3000 (default unless explicitly changed)"
echo "Influx server started on http://localhost:8086 (default unless explicitly changed)"

wait_for_service() {
  local name=$1
  local url=$2
  local max_retries=10
  local attempt=1

  echo "Waiting for $name at $url..."
  until curl -s "$url" >/dev/null; do
    if [ $attempt -ge $max_retries ]; then
      echo "$name did not respond at $url after $max_retries tries."
      exit 1
    fi
    printf "Attempt %d: %s not ready. Retrying in 2s...\n" "$attempt" "$name"
    sleep 2
    attempt=$((attempt+1))
  done
  echo "$name is running at $url"
}

# Extract values from file
GRAFANA_PORT=$(grep '^grafana_external=' default-values.txt | cut -d'=' -f2 | tr -d '"')
INFLUX_PORT=$(grep '^influxdb_external=' default-values.txt | cut -d'=' -f2 | tr -d '"')

GRAFANA_PORT=${GRAFANA_PORT:-3000}
INFLUX_PORT=${INFLUX_PORT:-8086}

# Check Grafana and InfluxDB
wait_for_service "Grafana" "http://localhost:$GRAFANA_PORT"
wait_for_service "InfluxDB" "http://localhost:$INFLUX_PORT"

