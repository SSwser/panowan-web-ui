import AppShell from './components/AppShell'
import { emptyRuntimeSummary } from './stores/runtimeStore'

export default function App() {
  return <AppShell runtime={emptyRuntimeSummary} />
}
