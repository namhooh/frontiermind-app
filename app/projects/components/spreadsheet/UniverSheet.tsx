'use client'

import '@univerjs/presets/lib/styles/preset-sheets-core.css'

import { useEffect, useRef, useCallback } from 'react'
import type { IWorkbookData } from '@univerjs/core'

interface UniverSheetProps {
  data: IWorkbookData | null
  onReady?: (api: UniverSheetAPI) => void
}

export interface UniverSheetAPI {
  getSnapshot: () => IWorkbookData | null
  dispose: () => void
}

export default function UniverSheet({ data, onReady }: UniverSheetProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<{ univer: unknown; univerAPI: unknown; wrapper: HTMLDivElement } | null>(null)
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady

  const dispose = useCallback(() => {
    if (instanceRef.current) {
      const inst = instanceRef.current
      instanceRef.current = null
      // Hide immediately to prevent visual overlap
      inst.wrapper.style.display = 'none'
      // Defer disposal out of React's synchronous render cycle
      setTimeout(() => {
        try {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ;(inst.univer as any)?.dispose()
        } catch {
          // Ignore disposal errors
        }
        try {
          inst.wrapper.remove()
        } catch {
          // Ignore removal errors
        }
      }, 0)
    }
  }, [])

  useEffect(() => {
    if (!containerRef.current || !data) return

    // Fresh child container for this Univer instance
    const wrapper = document.createElement('div')
    wrapper.style.cssText = 'width:100%;height:100%'
    containerRef.current.appendChild(wrapper)

    let cancelled = false

    async function init() {
      if (cancelled) { wrapper.remove(); return }

      // Dynamic imports to avoid SSR issues
      const [{ createUniver }, { UniverSheetsCorePreset }, sheetsLocale] = await Promise.all([
        import('@univerjs/presets'),
        import('@univerjs/presets/preset-sheets-core'),
        import('@univerjs/presets/preset-sheets-core/locales/en-US'),
      ])

      if (cancelled || !containerRef.current) { wrapper.remove(); return }

      const { univer, univerAPI } = createUniver({
        locale: 'enUS' as unknown as import('@univerjs/core').LocaleType,
        locales: { enUS: sheetsLocale.default },
        presets: [
          UniverSheetsCorePreset({
            container: wrapper,
            workerURL: false as unknown as string,
          }),
        ],
      })

      if (cancelled) {
        try { univer.dispose() } catch { /* noop */ }
        wrapper.remove()
        return
      }

      univer.createUniverSheet(data!)
      instanceRef.current = { univer, univerAPI, wrapper }

      // Expose API
      const api: UniverSheetAPI = {
        getSnapshot: () => {
          try {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const wb = (univerAPI as any).getActiveWorkbook()
            return wb?.save() ?? null
          } catch {
            return null
          }
        },
        dispose,
      }

      onReadyRef.current?.(api)
    }

    init()

    return () => {
      cancelled = true
      dispose()
    }
  }, [data, dispose])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', minHeight: 500 }}
    />
  )
}
