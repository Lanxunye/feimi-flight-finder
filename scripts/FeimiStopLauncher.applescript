try
  set launcherPath to (system attribute "HOME") & "/Library/Application Support/Feimi/scripts/feimi-stop.sh"
  do shell script quoted form of launcherPath
  display dialog "飞觅已彻底关闭。\n\n已停止网页、抓价、价格提醒和隔离登录窗口。再次打开“飞觅机票”即可重新启动。" buttons {"好"} default button "好" with icon note
on error errorMessage
  display dialog "飞觅关闭失败：" & return & errorMessage buttons {"好"} default button "好" with icon stop
end try
