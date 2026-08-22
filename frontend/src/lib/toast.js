let listeners = []

export function toast(msg, type = 'ok') {
  const item = { id: Date.now() + Math.random(), msg, type }
  listeners.forEach((f) => f(item))
}

export function onToast(fn) {
  listeners.push(fn)
  return () => {
    listeners = listeners.filter((x) => x !== fn)
  }
}
