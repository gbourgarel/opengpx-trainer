// Node resolve hook: extension-less relative imports (as written for Vite) -> ".ts".
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context)
  } catch (e) {
    if (e.code === 'ERR_MODULE_NOT_FOUND' && specifier.startsWith('.') && !specifier.endsWith('.ts')) {
      return next(specifier + '.ts', context)
    }
    throw e
  }
}
