variable "PUSH_BASE" {
  default = "false"
}

variable "PUSH_MINECRAFT" {
  default = "false"
}

variable "PUSH_FOUNDRY" {
  default = "false"
}

variable "PUSH_BACKUP" {
  default = "false"
}

variable "PUSH_AMBIENT_WEATHER" {
  default = "false"
}

variable "PUSH_SPEEDTEST" {
  default = "false"
}

variable "PUSH_HOST_STATUS" {
  default = "false"
}

group "default" {
  targets = ["base", "minecraft", "foundry", "backup", "ambient-weather-mqtt", "speedtest-mqtt", "host-status"]
}

target "base-meta" {}

target "minecraft-meta" {}

target "foundry-meta" {}

target "backup-meta" {}

target "ambient-weather-mqtt-meta" {}

target "speedtest-mqtt-meta" {}

target "host-status-meta" {}

target "base" {
  inherits = ["base-meta"]
  context = "base"
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_BASE == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "minecraft" {
  inherits = ["minecraft-meta"]
  context = "minecraft"
  contexts = {
    baseimage = "target:base"
  }
  args = {
    BASE_IMAGE = "baseimage"
  }
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_MINECRAFT == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "foundry" {
  inherits = ["foundry-meta"]
  context = "foundry"
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_FOUNDRY == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "backup" {
  inherits = ["backup-meta"]
  context = "backup"
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_BACKUP == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "ambient-weather-mqtt" {
  inherits = ["ambient-weather-mqtt-meta"]
  context = "ambient-weather-mqtt"
  contexts = {
    baseimage = "target:base"
  }
  args = {
    BASE_IMAGE = "baseimage"
  }
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_AMBIENT_WEATHER == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "speedtest-mqtt" {
  inherits = ["speedtest-mqtt-meta"]
  context = "speedtest-mqtt"
  contexts = {
    baseimage = "target:base"
  }
  args = {
    BASE_IMAGE = "baseimage"
  }
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_SPEEDTEST == "true" ? ["type=registry"] : ["type=cacheonly"]
}

target "host-status" {
  inherits = ["host-status-meta"]
  context = "host-status"
  platforms = ["linux/amd64", "linux/arm64"]
  output = PUSH_HOST_STATUS == "true" ? ["type=registry"] : ["type=cacheonly"]
}
