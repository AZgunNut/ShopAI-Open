#!/usr/bin/env bash
# Intentionally applies ONE AppArmor profile. Run as root on ShopAI only,
# after explicit interactive authorization on VirusLoaderMax.
set -Eeuo pipefail
P='/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth'
DEST='/etc/apparmor.d/bwrap-userns-restrict'
DISTRO='/usr/share/apparmor/extra-profiles/bwrap-userns-restrict'
CANDIDATE="$1"
EXPECTED="$2"
case "$CANDIDATE" in "$P"/tools/.shopai_aa_candidate.*) ;; *) echo 'STOP: unexpected staged profile path'; exit 3;; esac
[[ $EUID -eq 0 ]] || { echo 'STOP: requires sudo'; exit 3; }
[[ -x /usr/sbin/apparmor_parser ]] || { echo 'STOP: apparmor_parser unavailable';exit 3; }
[[ -x /usr/bin/bwrap ]] || { echo 'STOP: distro bwrap unavailable';exit 3; }
[[ -f "$CANDIDATE" && ! -L "$CANDIDATE" ]] || { echo 'STOP: missing staged fallback';exit 3; }
ACTUAL="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
[[ "$ACTUAL" == "$EXPECTED" ]] || { echo 'STOP: fallback SHA mismatch';exit 3; }
[[ ! -L "$DEST" ]] || { echo 'STOP: AppArmor path is a symlink; refusing to replace/reload automatically';exit 4; }
STAGE="$(mktemp /tmp/shopai-aa.XXXXXXXXXX)"
NEW=0
trap 'rm -f "$STAGE"' EXIT
if [[ -f "$DEST" ]]; then
  cp -p "$DEST" "$STAGE"
  echo 'Existing bwrap AppArmor profile found; checking and reloading WITHOUT overwriting.'
elif [[ -f "$DISTRO" ]]; then
  cp "$DISTRO" "$STAGE"
  echo 'Using the distribution supplied bwrap-userns-restrict profile.'
  NEW=1
else
  cp "$CANDIDATE" "$STAGE"
  echo 'Using bundled, reviewed Ubuntu 24.04-adapted restricted bwrap profile.'
  NEW=1
fi
# The standalone profile only needs to enable bwrap namespace construction.
# Never change kernel flags or other AppArmor profiles.
/usr/sbin/apparmor_parser -Q "$STAGE" >/dev/null
if [[ "$NEW" == 1 ]];then
  [[ ! -e "$DEST" ]] || { echo 'STOP: profile path appeared; refusing overwrite';exit 4; }
  install -m 0644 "$STAGE" "$DEST"
  if ! /usr/sbin/apparmor_parser -r "$DEST";then
    /usr/sbin/apparmor_parser -R "$DEST" >/dev/null 2>&1 || true
    rm -f "$DEST"
    echo 'ERROR: profile could not be loaded; newly installed file rolled back.'
    exit 5
  fi
  echo "NEW_PROFILE_INSTALLED=$DEST"
  echo "ROLLBACK_COMMAND=sudo apparmor_parser -R $DEST && sudo rm -- $DEST"
else
  /usr/sbin/apparmor_parser -r "$DEST"
  echo 'EXISTING_PROFILE_RELOADED; original file bytes unchanged.'
fi
[[ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns)" == 1 ]] || {
  echo 'WARNING: system-wide userns restriction was already disabled; this script did not change it.';
}
