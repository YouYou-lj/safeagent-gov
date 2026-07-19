import 'vue-router'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    title: string
    description: string
    icon: string
    order: number
  }
}
