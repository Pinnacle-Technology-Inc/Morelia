#!/bin/bash
sed -i 's/\r$//' start.sh

# Check if Anaconda is installed and install if not
if command -v conda &>/dev/null; then
    echo "Anaconda is already installed."
else
    echo "Anaconda is not installed. Installing now..."

    # Download Anaconda installer
    wget -q https://repo.anaconda.com/archive/Anaconda3-2023.03-Linux-x86_64.sh -O Anaconda3.sh

    if [ $? -eq 0 ]; then
        echo "Anaconda installer downloaded successfully."
    else
        echo "Failed to download Anaconda installer."
        exit 1
    fi

    # Run the Anaconda installer
    bash Anaconda3.sh -b

    if [ $? -eq 0 ]; then
        echo "Anaconda installation successful."
    else
        echo "Anaconda installation failed."
        exit 1
    fi

    # Remove the installer file after installation
    rm Anaconda3.sh

    # Initialize Anaconda and add it to the PATH
    echo "Initializing Anaconda..."
    source ~/anaconda3/bin/activate

    # Add Anaconda to PATH in .bashrc
    echo 'export PATH="~/anaconda3/bin:$PATH"' >> ~/.bashrc
    source ~/.bashrc

    # Verify installation
    if command -v conda &>/dev/null; then
        echo "Anaconda installed and configured successfully."
    else
        echo "Failed to set up Anaconda in PATH."
        exit 1
    fi
fi

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
sudo terraform apply -auto-approve

echo "Grafana server started on http://localhost:3000 (default unless explicitly changed)"
echo "Influx server started on http://localhost:8086 (default unless explicitly changed)"

# Detect new /dev/ttyUSB device and run the wsl-setup script to bind the new /dev/ttyUSB devices
chmod +x wsl-setup.sh
before=($(ls /dev/ttyUSB* 2>/dev/null))
       ./wsl-setup.sh "${before[@]}"
