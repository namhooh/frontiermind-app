type CacheEntry<T> = {
  data: T
  expiresAt: number
}

export interface ClientResourceCache<T> {
  get: (key: string) => T | null
  set: (key: string, data: T) => T
  getOrLoad: (key: string, loader: () => Promise<T>) => Promise<T>
  invalidate: (key?: string) => void
}

export function createClientResourceCache<T>(ttlMs: number): ClientResourceCache<T> {
  const cache = new Map<string, CacheEntry<T>>()
  const inflight = new Map<string, Promise<T>>()

  function get(key: string): T | null {
    const entry = cache.get(key)
    if (!entry) return null
    if (entry.expiresAt <= Date.now()) {
      cache.delete(key)
      return null
    }
    return entry.data
  }

  function set(key: string, data: T): T {
    cache.set(key, {
      data,
      expiresAt: Date.now() + ttlMs,
    })
    return data
  }

  async function getOrLoad(key: string, loader: () => Promise<T>): Promise<T> {
    const cached = get(key)
    if (cached !== null) return cached

    const pending = inflight.get(key)
    if (pending) return pending

    const request = loader()
      .then((data) => set(key, data))
      .finally(() => {
        inflight.delete(key)
      })

    inflight.set(key, request)
    return request
  }

  function invalidate(key?: string): void {
    if (key == null) {
      cache.clear()
      inflight.clear()
      return
    }
    cache.delete(key)
    inflight.delete(key)
  }

  return {
    get,
    set,
    getOrLoad,
    invalidate,
  }
}
