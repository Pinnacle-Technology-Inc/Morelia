resource "docker_image" "grafana" {
  name = "grafana/grafana-oss:latest"
}

resource "docker_container" "grafana" {
  name = "grafana_server"
  image = docker_image.grafana.image_id

  restart = "unless-stopped"

  ports {
    internal = var.grafana_internal
    external = var.grafana_external
  }

  networks_advanced {
    name = docker_network.monitoring.name
    aliases = ["grafana"]
  }

  env = [
    "GF_SECURITY_ADMIN_USER=${var.grafana_admin_user}",
    "GF_SECURITY_ADMIN_PASSWORD=${var.grafana_admin_password}"
  ] 

  //potentially add volumes here for logs or other persistent data
  
  mounts {
    target = "/etc/grafana/provisioning/dashboards"
    source = abspath("${path.module}/grafana/provisioning/dashboards")
    type = "bind"
  }

  mounts {
    target = "/var/lib/grafana/dashboards"
    source = abspath("${path.module}/grafana/dashboards")
    type = "bind"
  }

}

provider "grafana" {
  url = var.grafana_url
  auth = "${var.grafana_admin_user}:${var.grafana_admin_password}"
}

resource "grafana_data_source" "influxdb" {
  name = "InfluxDB"
  uid = "fepg8hwzyq9dsd"
  type = "influxdb"

  url = "http://influxdb:${var.influxdb_internal}"
  access_mode = "proxy"
  is_default = "true"
  
  json_data_encoded = jsonencode({
    version       = "Flux"
    organization  = var.influxdb_org
    defaultBucket = var.influxdb_bucket
  })

  secure_json_data_encoded = jsonencode({
    token = var.influxdb_token
  })

  depends_on = [docker_container.grafana]
}
