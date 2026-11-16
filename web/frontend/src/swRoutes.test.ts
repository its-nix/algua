import { expect, it } from 'vitest'
import { NavigationRoute } from 'workbox-routing'
import { NAV_DENYLIST } from './swRoutes'

it('lets OAuth start and callback navigate to the network while keeping offline app deep links', () => {
  const route = new NavigationRoute(async () => new Response('cached shell'), { denylist: NAV_DENYLIST })
  const request = new Request('https://dashboard.example.test/')
  Object.defineProperty(request, 'mode', { value: 'navigate' })
  const matches = (path: string) => route.match({
    url: new URL(path, request.url), request, sameOrigin: true, event: {} as ExtendableEvent,
  })
  expect(matches('/oauth2/start?rd=%2Fstrategies')).toBe(false)
  expect(matches('/oauth2/callback?code=example&state=example')).toBe(false)
  expect(matches('/strategies?sort=new')).toBe(true)
  expect(matches('/inbox')).toBe(true)
  expect(matches('/api/board')).toBe(false)
})
