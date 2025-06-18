variable "grafana_admin_user" {
  type = string
  description = "Admin username for Grafana"
  default = "admin"
}

variable "grafana_admin_password" {
  type = string
  description = "Admin password for Grafana"
  sensitive = true
}

variable "grafana_internal" {
  type = number
  description = "Internal port for Grafana"
}

variable "grafana_external" {
  type = number
  description = "External port for Grafana"
}


variable "grafana_url" {
  type = string
  description = "URL for Grafana instance"
  default = "http://localhost:3000"
}

variable "influxdb_admin_user" {
  type = string
  description = "Admin username for InfluxDB"
  sensitive = true
}

variable "influxdb_admin_password" {
  type = string
  description = "Admin password for InfluxDB"
  sensitive = true
}

variable "influxdb_token" {
  type = string
  description = "API token for InfluxDB"
  sensitive = true
}

variable "influxdb_org" {
  type = string
  description = "Organization for InfluxDB"
  default = "default-org"
}

variable "influxdb_bucket" {
  type = string
  description = "Initial bucket for InfluxDB"
  default = "default"
}

variable "influxdb_internal" {
  type = number
  description = "Internal port for InfluxDB"
}

variable "influxdb_external" {
  type = number
  description = "External port for InfluxDB"
}

variable "influxdb_url" {
  type = string
  description = "URL for InfluxDB instance"
  sensitive = true
}

