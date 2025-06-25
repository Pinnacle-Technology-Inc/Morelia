#!/bin/bash
sed -i 's/\r$//' start.sh
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
sudo terraform apply -auto-approve

echo "Grafana server started on http://localhost:3000 (default unless explicitly changed)"
echo "Influx server started on http://localhost:8086 (default unless explicitly changed)"

# Detect new /dev/ttyUSB device
chmod +x wsl-setup.sh
before=($(ls /dev/ttyUSB* 2>/dev/null))
       ./wsl-setup.sh "${before[@]}"

# Run the wsl-setup script to bind the new /dev/ttyUSB devices
bash wsl-setup.sh
