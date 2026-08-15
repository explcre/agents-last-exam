/* One episode: build a seeded arena, run a bot against it, read the final floor.

   The world is built and read through the server API, never through an opped bot,
   so the bot under test has no command access and has to dig for real.

   Usage: node episode.js <seed> <port> <bot.js> <out.json>
*/
const path = require('path')
const mc = require('flying-squid')
const { Vec3 } = require('vec3')
const registry = require('prismarine-registry')('1.16.5')

const VERSION = '1.16.5', SIZE = 7, HALF = (SIZE - 1) / 2
const MARKERS = ['white_wool', 'orange_wool', 'light_blue_wool']

function rng (seed) {
  let s = seed >>> 0 || 1
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296 }
}
function layout (seed, count = 14) {
  const r = rng(seed), taken = new Set(), out = []
  while (out.length < count) {
    const dx = Math.floor(r() * SIZE) - HALF, dz = Math.floor(r() * SIZE) - HALF
    const k = `${dx},${dz}`
    if (taken.has(k)) continue
    taken.add(k)
    out.push({ dx, dz, type: MARKERS[Math.floor(r() * MARKERS.length)] })
  }
  return out.sort((a, b) => a.dx - b.dx || a.dz - b.dz)
}

const id = name => registry.blocksByName[name].id

async function main () {
  const [seed, port, botPath, outPath] = [Number(process.argv[2]), Number(process.argv[3]),
    process.argv[4], process.argv[5]]
  const server = mc.createMCServer({ 'online-mode': false, port, version: VERSION,
    gameMode: 1, difficulty: 0  /* creative: digging is instant, so an episode is seconds not minutes */, worldFolder: null,
    generation: { name: 'superflat', options: { seed: 1 } }, kickTimeout: 120000, plugins: {},
    'view-distance': 4, 'everybody-op': false, logging: false,
    'player-list-text': { header: '', footer: '' }, 'max-entities': 50 })
  await new Promise(r => server.on('listening', r))
  const world = server.overworld

  // The spawn point is not fixed across server instances, so the arena is centred on
  // wherever players spawn and its bounds are handed to the bot explicitly.
  const mineflayer = require('mineflayer')
  const probe = mineflayer.createBot({ host: '127.0.0.1', port, username: 'probe', version: VERSION })
  await new Promise((res, rej) => { probe.once('spawn', res); probe.once('error', rej) })
  await probe.waitForTicks(10)
  const o = probe.entity.position.floored()
  const centre = new Vec3(o.x, o.y - 1, o.z)
  probe.quit()
  await new Promise(r => setTimeout(r, 400))

  for (let dx = -HALF; dx <= HALF; dx++)
    for (let dz = -HALF; dz <= HALF; dz++)
      await world.setBlockType(centre.offset(dx, 0, dz), id('grass_block'))
  for (const m of layout(seed))
    await world.setBlockType(centre.offset(m.dx, 0, m.dz), id(m.type))

  const read = async () => {
    const g = {}
    for (let dx = -HALF; dx <= HALF; dx++)
      for (let dz = -HALF; dz <= HALF; dz++) {
        const b = await world.getBlock(centre.offset(dx, 0, dz))
        g[`${dx},${dz}`] = b ? b.name : 'unknown'
      }
    return g
  }
  const before = await read()

  const arena = { centre: [centre.x, centre.y, centre.z], size: SIZE, host: '127.0.0.1', port,
                  version: VERSION, username: 'digger' }
  require('fs').writeFileSync(path.join(path.dirname(outPath), 'arena.json'), JSON.stringify(arena))

  let err = null
  try {
    const mod = require(path.resolve(botPath))
    const run = typeof mod === 'function' ? mod : mod.run
    await Promise.race([
      run(arena),
      new Promise((_, rej) => setTimeout(() => rej(new Error('bot timeout')), 240000))
    ])
  } catch (e) { err = e.message.slice(0, 200) }

  const after = await read()
  require('fs').writeFileSync(outPath, JSON.stringify({ seed, before, after, err }, null, 1))
  console.log(`seed ${seed}: ${Object.keys(after).filter(k => before[k] !== after[k]).length} cells changed` +
              (err ? `  ERROR: ${err}` : ''))
  process.exit(0)
}
main().catch(e => { console.error('EPISODE FAILED:', e.message); process.exit(1) })
