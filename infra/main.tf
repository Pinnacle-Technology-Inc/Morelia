terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0.1"
    }
    influxdb = {
      source  = "komminarlabs/influxdb"
      version = "~> 1.1.2"
    }
    //grafana = {
      //source  = "grafana/grafana"
      //version = "~> 2.0"
    //}
  }
}


provider "docker" {}
