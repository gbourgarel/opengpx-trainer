import { useState } from 'react'
import { api, type DeviceStatus, type Profile, type ScanDevice, type ScanResult } from '../api'

export type DeviceRole = 'trainer' | 'power_meter' | 'heart_rate'
type Setter = <K extends keyof Profile>(k: K, v: Profile[K]) => void

const ROLES: [DeviceRole, string][] = [
  ['trainer', 'Trainer'],
  ['power_meter', 'Power meter'],
  ['heart_rate', 'Heart rate'],
]
const ROLE_LABEL = Object.fromEntries(ROLES) as Record<DeviceRole, string>

const shortId = (id: string) => (id.length > 12 ? `${id.slice(0, 8)}…` : id)

function RoleRow({ role, label, p, set, live }: { role: DeviceRole; label: string; p: Profile; set: Setter; live?: DeviceStatus }) {
  const transport = p[`${role}_transport`]
  const number = p[`${role}_device_number`]
  const bleId = p[`${role}_ble_id`]
  const bleName = p[`${role}_ble_name`]
  const connected = live?.connected
  const liveDesc = connected ? (live?.transport === 'ble' ? live?.name ?? shortId(live?.ble_id ?? '') : live?.device_number) : null
  const mismatch = connected && (transport !== live?.transport || (transport === 'ant' ? number != null && number !== live?.device_number : bleId !== live?.ble_id))

  return (
    <div className="role-row">
      <span className="role-label">{label}</span>
      <div className="seg">
        <button type="button" className={transport === 'ant' ? 'on' : ''} onClick={() => set(`${role}_transport`, 'ant')}>
          ANT+
        </button>
        <button type="button" className={transport === 'ble' ? 'on' : ''} onClick={() => set(`${role}_transport`, 'ble')}>
          Bluetooth
        </button>
      </div>
      {transport === 'ant' ? (
        <div className="dev-field">
          <input
            type="number"
            min={1}
            max={65535}
            placeholder="first found"
            value={number ?? ''}
            onChange={(e) => set(`${role}_device_number`, e.target.value === '' ? null : Number(e.target.value))}
          />
          {number != null && (
            <button className="ghost" type="button" onClick={() => set(`${role}_device_number`, null)} title="Clear: pair with the first device found">
              ✕
            </button>
          )}
        </div>
      ) : (
        <div className="dev-field ble-choice">
          {bleId ? (
            <>
              <b>{bleName ?? 'device'}</b> <small className="muted">{shortId(bleId)}</small>
              <button
                className="ghost"
                type="button"
                title="Clear"
                onClick={() => {
                  set(`${role}_ble_id`, null)
                  set(`${role}_ble_name`, null)
                }}
              >
                ✕
              </button>
            </>
          ) : (
            <span className="warn-text">none chosen — scan below</span>
          )}
        </div>
      )}
      <small className="muted role-live">
        {connected ? (
          <>
            connected: <b className={mismatch ? 'warn' : ''}>{liveDesc}</b> ({live?.transport === 'ble' ? 'Bluetooth' : 'ANT+'})
          </>
        ) : (
          'not connected'
        )}
      </small>
    </div>
  )
}

export function DevicesCard({ p, set, devices }: { p: Profile; set: Setter; devices?: Record<DeviceRole, DeviceStatus> }) {
  const [scanning, setScanning] = useState(false)
  const [result, setResult] = useState<ScanResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const scan = () => {
    setScanning(true)
    setError(null)
    api
      .scan(6)
      .then(setResult)
      .catch((e: Error) => setError(e.message))
      .finally(() => setScanning(false))
  }

  const use = (d: ScanDevice, role: DeviceRole) => {
    set(`${role}_transport`, d.transport)
    if (d.transport === 'ant') set(`${role}_device_number`, d.device_number ?? null)
    else {
      set(`${role}_ble_id`, d.ble_id ?? null)
      set(`${role}_ble_name`, d.name ?? null)
    }
  }

  const chosen = (d: ScanDevice, role: DeviceRole) =>
    p[`${role}_transport`] === d.transport && (d.transport === 'ant' ? p[`${role}_device_number`] === d.device_number : p[`${role}_ble_id`] === d.ble_id)

  const rows = result ? [...result.ant, ...result.ble] : []

  return (
    <div className="card">
      <h3>Devices</h3>
      <p className="muted">
        Pick the protocol and the device for each sensor. ANT+ with no number = first device found; Bluetooth needs a device chosen from a scan. The trainer's own
        power broadcast is never used as the power meter. Saving the profile reconnects the sensors when no ride is in progress.
      </p>
      {ROLES.map(([role, label]) => (
        <RoleRow key={role} role={role} label={label} p={p} set={set} live={devices?.[role]} />
      ))}

      <div className="toolbar scan-bar">
        <button type="button" onClick={scan} disabled={scanning}>
          {scanning ? 'Scanning ANT+ and Bluetooth… (6 s)' : 'Scan for devices'}
        </button>
        <small className="muted">Connected sensors stay connected during the scan.</small>
      </div>
      {error && <div className="error">{error}</div>}
      {result && (
        <>
          {Object.entries(result.errors).map(([k, v]) => (
            <div key={k} className="error">
              {k === 'ant' ? 'ANT+' : k === 'ble' ? 'Bluetooth' : 'Reconnect'}: {v}
            </div>
          ))}
          {rows.length === 0 ? (
            <p className="muted">No sensor found. Wake them up (pedal, wear the strap) and scan again.</p>
          ) : (
            <table className="scan-table">
              <thead>
                <tr>
                  <th>Protocol</th>
                  <th>Device</th>
                  <th>Type</th>
                  <th>Signal</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.transport === 'ant' ? `ant-${d.device_number}-${d.device_type}` : `ble-${d.ble_id}`} className={d.roles.length ? '' : 'dim'}>
                    <td>{d.transport === 'ant' ? 'ANT+' : 'Bluetooth'}</td>
                    <td>
                      {d.transport === 'ant' ? (
                        <b>#{d.device_number}</b>
                      ) : (
                        <>
                          <b>{d.name}</b> <small className="muted">{shortId(d.ble_id ?? '')}</small>
                        </>
                      )}
                    </td>
                    <td>
                      {d.transport === 'ant' ? d.label : d.roles.map((r) => ROLE_LABEL[r as DeviceRole]).join(', ')}
                      {d.note && <small className="muted"> — {d.note}</small>}
                    </td>
                    <td className="muted">{d.transport === 'ble' ? `${d.rssi} dBm` : `${d.messages} msg`}</td>
                    <td>
                      {/* flex on an inner div: a flex <td> leaves the table layout (misaligned row borders) */}
                      <div className="scan-actions">
                        {(d.roles as DeviceRole[]).map((role) =>
                          chosen(d, role) ? (
                            <span key={role} className="badge">
                              {ROLE_LABEL[role]} ✓
                            </span>
                          ) : (
                            <button key={role} type="button" onClick={() => use(d, role)}>
                              Use as {ROLE_LABEL[role].toLowerCase()}
                            </button>
                          ),
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <small className="muted">Choices are applied when you save the profile.</small>
        </>
      )}
    </div>
  )
}
