//resource "docker_image" "grafana" {
//  name = "grafana/grafana-oss:latest"
//}
//
//resource "docker_container" "grafana" {
//  name = "grafana"
//  image = docker_image.grafana.latest
//
//  ports {
//    internal = var.grafana_internal
//    external = var.grafana_external
//  }
//}
//
//provider "grafana" {
//  url = 
//  auth = "admin:admin123"
//}
