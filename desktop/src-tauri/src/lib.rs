use serde::{Deserialize, Serialize};
use std::{
    net::{SocketAddr, TcpListener, TcpStream},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const READY_PREFIX: &str = "SAFEAGENT_DESKTOP_READY ";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopBootstrap {
    api_base_url: String,
    token: String,
    data_dir: String,
    pid: u32,
}

#[derive(Default)]
struct DesktopState {
    bootstrap: Mutex<Option<DesktopBootstrap>>,
    child: Mutex<Option<CommandChild>>,
    failure: Mutex<Option<String>>,
}

fn parse_ready_line(line: &[u8]) -> Result<Option<DesktopBootstrap>, String> {
    let text = std::str::from_utf8(line).map_err(|_| "Sidecar 输出不是 UTF-8".to_string())?;
    let Some(payload) = text.trim().strip_prefix(READY_PREFIX) else {
        return Ok(None);
    };
    serde_json::from_str(payload)
        .map(Some)
        .map_err(|error| format!("Sidecar 启动信息无效: {error}"))
}

fn available_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("无法分配本地端口: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("无法读取本地端口: {error}"))
}

fn wait_for_loopback(api_base_url: &str) -> Result<(), String> {
    let port = api_base_url
        .strip_prefix("http://127.0.0.1:")
        .ok_or_else(|| "Sidecar API 地址不是受控回环地址".to_string())?
        .parse::<u16>()
        .map_err(|_| "Sidecar API 端口无效".to_string())?;
    for _ in 0..100 {
        let address = SocketAddr::from(([127, 0, 0, 1], port));
        if TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("Sidecar 回环健康探测超时".to_string())
}

fn start_sidecar(app: &AppHandle) -> Result<(), String> {
    let port = available_port()?;
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("无法确定应用数据目录: {error}"))?;
    let command = app
        .shell()
        .sidecar("safeagent-backend")
        .map_err(|error| format!("无法定位安全 Sidecar: {error}"))?
        .args([
            "--port".to_string(),
            port.to_string(),
            "--data-dir".to_string(),
            data_dir.to_string_lossy().into_owned(),
            "--parent-pid".to_string(),
            std::process::id().to_string(),
        ]);
    let (mut events, child) = command
        .spawn()
        .map_err(|error| format!("无法启动安全 Sidecar: {error}"))?;
    *app.state::<DesktopState>()
        .child
        .lock()
        .map_err(|_| "Sidecar 状态锁损坏")? = Some(child);

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => match parse_ready_line(&bytes) {
                    Ok(Some(bootstrap)) => {
                        let probe_handle = handle.clone();
                        thread::spawn(move || match wait_for_loopback(&bootstrap.api_base_url) {
                            Ok(()) => {
                                if let Ok(mut state) =
                                    probe_handle.state::<DesktopState>().bootstrap.lock()
                                {
                                    *state = Some(bootstrap);
                                }
                            }
                            Err(error) => {
                                if let Ok(mut failure) =
                                    probe_handle.state::<DesktopState>().failure.lock()
                                {
                                    *failure = Some(error);
                                }
                            }
                        });
                    }
                    Ok(None) => {}
                    Err(error) => {
                        if let Ok(mut failure) = handle.state::<DesktopState>().failure.lock() {
                            *failure = Some(error);
                        }
                    }
                },
                CommandEvent::Error(error) => {
                    let message = error.trim().to_string();
                    if !message.is_empty() {
                        eprintln!("SafeAgent Sidecar: {message}");
                    }
                }
                CommandEvent::Terminated(status) => {
                    let ready = handle
                        .state::<DesktopState>()
                        .bootstrap
                        .lock()
                        .map(|value| value.is_some())
                        .unwrap_or(false);
                    if !ready {
                        if let Ok(mut failure) = handle.state::<DesktopState>().failure.lock() {
                            *failure = Some(format!("安全 Sidecar 提前退出: {:?}", status.code));
                        }
                    }
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

#[tauri::command]
fn desktop_bootstrap(state: State<'_, DesktopState>) -> Result<DesktopBootstrap, String> {
    if let Some(value) = state
        .bootstrap
        .lock()
        .map_err(|_| "桌面启动状态锁损坏")?
        .clone()
    {
        return Ok(value);
    }
    if let Some(error) = state
        .failure
        .lock()
        .map_err(|_| "桌面错误状态锁损坏")?
        .clone()
    {
        return Err(error);
    }
    Err("本地安全服务正在启动".to_string())
}

pub fn run() {
    let app = tauri::Builder::default()
        .manage(DesktopState::default())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![desktop_bootstrap])
        .setup(|app| start_sidecar(app.handle()).map_err(Into::into))
        .build(tauri::generate_context!())
        .expect("failed to build GovSafeAgent desktop application");

    app.run(|handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Ok(mut child) = handle.state::<DesktopState>().child.lock() {
                if let Some(process) = child.take() {
                    let _ = process.kill();
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_only_prefixed_ready_records() {
        assert!(parse_ready_line(b"ordinary log").unwrap().is_none());
        let record = parse_ready_line(
            br#"SAFEAGENT_DESKTOP_READY {"apiBaseUrl":"http://127.0.0.1:8765","token":"abc","dataDir":"/tmp/app","pid":42}"#,
        )
        .unwrap()
        .unwrap();
        assert_eq!(record.api_base_url, "http://127.0.0.1:8765");
        assert_eq!(record.pid, 42);
    }

    #[test]
    fn rejects_malformed_ready_records() {
        assert!(parse_ready_line(b"SAFEAGENT_DESKTOP_READY not-json").is_err());
    }

    #[test]
    fn rejects_non_loopback_probe_targets() {
        assert!(wait_for_loopback("https://example.com:443").is_err());
        assert!(wait_for_loopback("http://localhost:8765").is_err());
    }
}
