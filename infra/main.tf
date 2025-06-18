terraform {
  required_providers {
    influxdb = {
      source  = "komminarlabs/influxdb"
      version = "~> 1.1.2"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0.1"
    }
 
  }
}

provider "docker" {}

resource "docker_image" "influxdb" {
  name         = "influxdb:latest"
}

resource "docker_volume" "influx-sink-influx-data" {
  name = "influx-sink-influx-data"
}

resource "docker_volume" "influx-sink-influx-config" {
  name = "influx-sink-influx-config"
}

resource "docker_container" "influxdb" {

  image = docker_image.influxdb.image_id
  name  = "influxdb_server"

  ports {
    internal = 8086
    external = 8086
  }

  env = [ "DOCKER_INFLUXDB_INIT_MODE=setup"
        , "DOCKER_INFLUXDB_INIT_USERNAME=admin"
        , "DOCKER_INFLUXDB_INIT_PASSWORD=admin123!!"
        , "DOCKER_INFLUXDB_INIT_ORG=pinnacle-technology"
        , "DOCKER_INFLUXDB_INIT_BUCKET=default"
        , "DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=blah123!!blah"
        ]

  volumes {
    volume_name = "influx-sink-influx-data"
    container_path = "/var/lib/influxdb2"
  }

  volumes {
    volume_name = "influx-sink-influx-config"
    container_path = "/etc/influxdb2"
  }

}

provider "influxdb" {}

resource "influxdb_authorization" "token" {
  org_id = "8fefa4abaf1a866e"
  permissions = [ {
    action = "write"
    resource = {
      type = "buckets"
    }
  } ]
}

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

//resource "docker_image" "grafana" {
//  name = "grafana/grafana-oss:latest"
//}
//
//resource "docker_container" "grafana" {
//  name = "grafana"
//  image = docker_image.grafana.latest
//
//  ports {
//    internal = 3000
//    external = 3000
//  }
//}
