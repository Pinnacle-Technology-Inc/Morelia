resource "docker_image" "influxdb" {
  count = var.use_influxdb ? 1 : 0
  name  = "influxdb:latest"
}

resource "docker_volume" "influx-sink-influx-data" {
  count = var.use_influxdb ? 1 : 0
  name  = "influx-sink-influx-data"
}

resource "docker_volume" "influx-sink-influx-config" {
  count = var.use_influxdb ? 1 : 0
  name  = "influx-sink-influx-config"
}

resource "docker_container" "influxdb" {
  count = var.use_influxdb ? 1 : 0

  image = docker_image.influxdb[0].image_id
  name  = "influxdb_server"

  ports {
    internal = var.influxdb_internal
    external = var.influxdb_external
  }

  networks_advanced {
    name    = docker_network.monitoring.name
    aliases = ["influxdb"]
  }

  env = [
    "DOCKER_INFLUXDB_INIT_MODE=setup",
    "DOCKER_INFLUXDB_INIT_USERNAME=${var.influxdb_admin_user}",
    "DOCKER_INFLUXDB_INIT_PASSWORD=${var.influxdb_admin_password}",
    "DOCKER_INFLUXDB_INIT_ORG=${var.influxdb_org}",
    "DOCKER_INFLUXDB_INIT_BUCKET=${var.influxdb_bucket}",
    "DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=${var.influxdb_token}"
  ]

  volumes {
    volume_name    = docker_volume.influx-sink-influx-data[0].name
    container_path = "/var/lib/influxdb2"
  }

  volumes {
    volume_name    = docker_volume.influx-sink-influx-config[0].name
    container_path = "/etc/influxdb2"
  }
}

provider "influxdb" {

  url   = var.influxdb_url
  token = var.influxdb_token
}


//resource "influxdb_authorization" "token" {
//  org_id = "8fefa4abaf1a866e"
//  permissions = [ {
//    action = "write"
//    resource = {
//      type = "buckets"
//    }
//  } ]
//}

// TODO: switch to env vars
//provider "influxdb" {
//  token = "blah123!!blah"
//  url   = "http://localhost:8086"
//}
//
//resource "influxdb_authorization" "main_token" {
//
//}
//
//resource "influxdb_organization" "pinnacle-technology" {
//  name = "pinnacle-technology"
//  description = "Data collected by Pinnacle Technology dveices."
//}

