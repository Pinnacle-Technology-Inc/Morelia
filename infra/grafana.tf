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
  type = "influxdb"

  url = "http://host.docker.internal:8181"
  access_mode = "proxy"
  is_default = "true"
  
  json_data = jsonencode({
    version       = "Flux"
    organization  = "pinnacle-technology"
    defaultBucket = "default"
  })

  secure_json_data = {
    token = var.influxdb_token
  }
  depends_on = [docker_container.grafana]
}
