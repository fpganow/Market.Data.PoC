<?php
/**
 * Plugin Name: FPGA Now - Run on Hardware
 * Description: Replays one of the pre-canned CBOE PITCH test pcaps against the live FPGA board (LabVIEW FPGA or Verilog parser) through the hwrun service and shows every parsed message with its latency: table, CSV download and chart. Shortcode: [fpganow_hwrun]
 * Version: 1.2.0
 * Author: FPGA Now
 * License: GPL-2.0-or-later
 *
 * The page talks only to this site's REST API (fpganow-hwrun/v1/...); the plugin forwards the
 * calls server-side to the run service (Market.Data.PoC/tools/hwrun/hwrun_server.py) with a
 * bearer token, so the service and its token are never exposed to the browser. Settings ->
 * Run on Hardware holds the service URL, the token and the per-visitor cooldown; the constants
 * FPGANOW_HWRUN_URL / FPGANOW_HWRUN_TOKEN in wp-config.php override them.
 *
 * Since 1.2.0 starting a run needs a signed-in account (setting "Require sign-in"). Visitors sign
 * in with Google on the page itself: the browser gets an ID token from Google Identity Services,
 * the plugin checks it with Google (tokeninfo), then finds or creates a subscriber account for that
 * verified e-mail address and logs it in. Only a Google OAuth client ID is needed, no secret.
 * Accounts registered through wp-login.php (e-mail + password) may run only if the setting
 * "Also allow e-mail accounts" is on; editors and administrators always may.
 */
if (!defined('ABSPATH')) { exit; }

define('FPGANOW_HWRUN_VERSION', '1.2.0');
define('FPGANOW_HWRUN_NS', 'fpganow-hwrun/v1');

function fpganow_hwrun_url() {
    $u = defined('FPGANOW_HWRUN_URL') ? FPGANOW_HWRUN_URL : get_option('fpganow_hwrun_url', 'http://host.docker.internal:8300');
    return rtrim($u, '/');
}
function fpganow_hwrun_token() {
    return defined('FPGANOW_HWRUN_TOKEN') ? FPGANOW_HWRUN_TOKEN : (string) get_option('fpganow_hwrun_token', '');
}
function fpganow_hwrun_cooldown() {
    return max(0, (int) get_option('fpganow_hwrun_cooldown', 20));
}
function fpganow_hwrun_google_client_id() {
    return trim(defined('FPGANOW_HWRUN_GOOGLE_CLIENT_ID') ? FPGANOW_HWRUN_GOOGLE_CLIENT_ID : (string) get_option('fpganow_hwrun_google_client_id', ''));
}
function fpganow_hwrun_require_login() {
    return (bool) get_option('fpganow_hwrun_require_login', 1);
}
function fpganow_hwrun_allow_email_accounts() {
    return (bool) get_option('fpganow_hwrun_allow_email_accounts', 0);
}
/** May the current visitor start a run? */
function fpganow_hwrun_user_may_run() {
    if (!fpganow_hwrun_require_login()) { return true; }
    if (!is_user_logged_in()) { return false; }
    if (current_user_can('edit_posts')) { return true; }
    if (get_user_meta(get_current_user_id(), 'fpganow_google_sub', true)) { return true; }
    return fpganow_hwrun_allow_email_accounts();
}
// accounts created for the run page have no business in wp-admin: no toolbar for them on the site
add_filter('show_admin_bar', function ($show) { return current_user_can('edit_posts') ? $show : false; });

/* ---------------------------------------------------------------- settings */
add_action('admin_menu', function () {
    add_options_page('Run on Hardware', 'Run on Hardware', 'manage_options', 'fpganow-hwrun', 'fpganow_hwrun_settings_page');
});
add_action('admin_init', function () {
    register_setting('fpganow_hwrun', 'fpganow_hwrun_url', ['sanitize_callback' => 'esc_url_raw']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_token', ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_cooldown', ['sanitize_callback' => 'absint']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_require_login', ['sanitize_callback' => 'absint']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_allow_email_accounts', ['sanitize_callback' => 'absint']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_google_client_id', ['sanitize_callback' => 'sanitize_text_field']);
});
function fpganow_hwrun_settings_page() {
    if (!current_user_can('manage_options')) { return; }
    $probe = fpganow_hwrun_request('GET', '/api/catalog');
    ?>
    <div class="wrap">
      <h1>Run on Hardware</h1>
      <p>Put the shortcode <code>[fpganow_hwrun]</code> on a page. The service is
         <code>Market.Data.PoC/tools/hwrun/hwrun_server.py</code> on the PC that is cabled to the board.</p>
      <form method="post" action="options.php">
        <?php settings_fields('fpganow_hwrun'); ?>
        <table class="form-table" role="presentation">
          <tr><th scope="row"><label for="fpganow_hwrun_url">Service URL</label></th>
              <td><input name="fpganow_hwrun_url" id="fpganow_hwrun_url" type="url" class="regular-text"
                         value="<?php echo esc_attr(get_option('fpganow_hwrun_url', 'http://host.docker.internal:8300')); ?>"
                         <?php disabled(defined('FPGANOW_HWRUN_URL')); ?>>
                  <p class="description">From inside the WordPress container, <code>host.docker.internal:8300</code> is the Docker host.</p></td></tr>
          <tr><th scope="row"><label for="fpganow_hwrun_token">Bearer token</label></th>
              <td><input name="fpganow_hwrun_token" id="fpganow_hwrun_token" type="password" class="regular-text"
                         value="<?php echo esc_attr(get_option('fpganow_hwrun_token', '')); ?>" <?php disabled(defined('FPGANOW_HWRUN_TOKEN')); ?>>
                  <p class="description">Contents of <code>tools/hwrun/token</code> on the service PC.</p></td></tr>
          <tr><th scope="row"><label for="fpganow_hwrun_cooldown">Cooldown per visitor (s)</label></th>
              <td><input name="fpganow_hwrun_cooldown" id="fpganow_hwrun_cooldown" type="number" min="0" class="small-text"
                         value="<?php echo esc_attr(fpganow_hwrun_cooldown()); ?>">
                  <p class="description">Minimum time between two runs started by the same account (or IP address when sign-in is off).</p></td></tr>
          <tr><th scope="row">Sign-in</th>
              <td><label><input name="fpganow_hwrun_require_login" type="checkbox" value="1" <?php checked(fpganow_hwrun_require_login()); ?>>
                    Require sign-in to start a run</label><br>
                  <label><input name="fpganow_hwrun_allow_email_accounts" type="checkbox" value="1" <?php checked(fpganow_hwrun_allow_email_accounts()); ?>>
                    Also allow e-mail accounts (registered through wp-login.php, not Google)</label>
                  <p class="description">With the second box off, only accounts that signed in with Google (and editors/administrators) can start runs.</p></td></tr>
          <tr><th scope="row"><label for="fpganow_hwrun_google_client_id">Google client ID</label></th>
              <td><input name="fpganow_hwrun_google_client_id" id="fpganow_hwrun_google_client_id" type="text" class="large-text"
                         value="<?php echo esc_attr(fpganow_hwrun_google_client_id()); ?>" <?php disabled(defined('FPGANOW_HWRUN_GOOGLE_CLIENT_ID')); ?>
                         placeholder="1234567890-abc...apps.googleusercontent.com">
                  <p class="description">Google Cloud console &rarr; APIs &amp; Services &rarr; Credentials &rarr; Create OAuth client ID &rarr; Web application.
                     Authorised JavaScript origin: <code><?php echo esc_html(set_url_scheme(home_url(), 'https')); ?></code>. No redirect URI and no client secret are needed.</p></td></tr>
        </table>
        <?php submit_button(); ?>
      </form>
      <h2>Service status</h2>
      <?php if (is_wp_error($probe)) : ?>
        <p style="color:#b32d2e"><strong>Not reachable:</strong> <?php echo esc_html($probe->get_error_message()); ?></p>
      <?php elseif ($probe->get_status() !== 200) : ?>
        <p style="color:#b32d2e"><strong>Service answered HTTP <?php echo (int) $probe->get_status(); ?></strong>
           (wrong token?)</p>
      <?php else : $c = $probe->get_data(); ?>
        <p style="color:#00a32a"><strong>Reachable.</strong>
           <?php echo (int) count($c['pcaps'] ?? []); ?> pcaps,
           <?php echo (int) count($c['implementations'] ?? []); ?> implementations,
           <?php echo (int) count($c['boards'] ?? []); ?> board(s);
           <?php foreach (($c['boards'] ?? []) as $k => $b) { echo esc_html($k . ': loaded app ' . ($b['loaded_app'] ?? 'unknown') . '. '); } ?>
           <?php echo !empty($c['busy']) ? 'A run is in progress.' : 'Idle.'; ?></p>
      <?php endif; ?>
    </div>
    <?php
}

/* ------------------------------------------------------------------- proxy */
/** Forward one call to the run service. Returns WP_REST_Response (any status) or WP_Error. */
function fpganow_hwrun_request($method, $path, $body = null, $raw = false) {
    $args = ['method' => $method, 'timeout' => 25, 'headers' => ['Accept' => $raw ? '*/*' : 'application/json']];
    $t = fpganow_hwrun_token();
    if ($t !== '') { $args['headers']['Authorization'] = 'Bearer ' . $t; }
    if ($body !== null) { $args['headers']['Content-Type'] = 'application/json'; $args['body'] = wp_json_encode($body); }
    $r = wp_remote_request(fpganow_hwrun_url() . $path, $args);
    if (is_wp_error($r)) {
        return new WP_Error('hwrun_unreachable', 'The hardware run service is not reachable: ' . $r->get_error_message(), ['status' => 502]);
    }
    $code = (int) wp_remote_retrieve_response_code($r);
    $text = wp_remote_retrieve_body($r);
    if ($raw) { return new WP_REST_Response($text, $code); }
    $json = json_decode($text, true);
    if (!is_array($json)) {
        return new WP_Error('hwrun_bad_response', 'Unexpected answer from the run service (HTTP ' . $code . ')', ['status' => 502]);
    }
    return new WP_REST_Response($json, $code);
}

function fpganow_hwrun_client_ip() {
    return isset($_SERVER['REMOTE_ADDR']) ? sanitize_text_field(wp_unslash($_SERVER['REMOTE_ADDR'])) : '0.0.0.0';
}

function fpganow_hwrun_start(WP_REST_Request $req) {
    // a custom header forces a CORS preflight, so other origins cannot start runs from a visitor's browser
    if ($req->get_header('x-fpganow-hwrun') !== '1') {
        return new WP_Error('hwrun_forbidden', 'Missing request header', ['status' => 403]);
    }
    if (!fpganow_hwrun_user_may_run()) {
        return new WP_Error('hwrun_login', is_user_logged_in()
            ? 'This account cannot start runs. Sign in with Google.' : 'Sign in to start a run.', ['status' => 401]);
    }
    $key = 'fpganow_hwrun_rl_' . (is_user_logged_in() ? 'u' . get_current_user_id() : md5(fpganow_hwrun_client_ip()));
    $cool = fpganow_hwrun_cooldown();
    if ($cool > 0 && get_transient($key)) {
        return new WP_Error('hwrun_cooldown', 'Please wait ' . $cool . ' seconds between runs.', ['status' => 429]);
    }
    $sel = [
        'pcap'           => sanitize_key((string) $req->get_param('pcap')),
        'implementation' => sanitize_key((string) $req->get_param('implementation')),
        'board'          => sanitize_key((string) $req->get_param('board')),
    ];
    $speed = sanitize_key((string) $req->get_param('speed'));
    if ($speed !== '') { $sel['speed'] = $speed; }   // optional; the service falls back to its default
    $r = fpganow_hwrun_request('POST', '/api/runs', $sel);
    if (!is_wp_error($r) && $r->get_status() === 202 && $cool > 0) { set_transient($key, 1, $cool); }
    return $r;
}

/**
 * Sign in with Google: verify the ID token the browser got from Google Identity Services, then
 * log in the account for that verified e-mail address, creating a subscriber if there is none.
 */
function fpganow_hwrun_google_login(WP_REST_Request $req) {
    if ($req->get_header('x-fpganow-hwrun') !== '1') {
        return new WP_Error('hwrun_forbidden', 'Missing request header', ['status' => 403]);
    }
    $cid = fpganow_hwrun_google_client_id();
    if ($cid === '') { return new WP_Error('hwrun_google_off', 'Google sign-in is not configured.', ['status' => 503]); }
    $rl = 'fpganow_hwrun_gl_' . md5(fpganow_hwrun_client_ip());
    $tries = (int) get_transient($rl);
    if ($tries >= 10) { return new WP_Error('hwrun_cooldown', 'Too many sign-in attempts, try again later.', ['status' => 429]); }
    set_transient($rl, $tries + 1, 10 * MINUTE_IN_SECONDS);

    $cred = (string) $req->get_param('credential');
    if ($cred === '' || strlen($cred) > 4096 || !preg_match('/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/', $cred)) {
        return new WP_Error('hwrun_google_bad', 'Malformed sign-in token.', ['status' => 400]);
    }
    $r = wp_remote_get('https://oauth2.googleapis.com/tokeninfo?id_token=' . rawurlencode($cred), ['timeout' => 10]);
    if (is_wp_error($r)) { return new WP_Error('hwrun_google_unreachable', 'Could not reach Google to check the sign-in.', ['status' => 502]); }
    $t = json_decode(wp_remote_retrieve_body($r), true);
    $ok = (int) wp_remote_retrieve_response_code($r) === 200 && is_array($t)
        && isset($t['aud'], $t['iss'], $t['exp'], $t['sub'], $t['email'])
        && hash_equals($cid, (string) $t['aud'])
        && in_array($t['iss'], ['accounts.google.com', 'https://accounts.google.com'], true)
        && (int) $t['exp'] > time()
        && in_array($t['email_verified'] ?? false, [true, 'true'], true)
        && is_email($t['email']);
    if (!$ok) { return new WP_Error('hwrun_google_rejected', 'Google did not confirm this sign-in.', ['status' => 401]); }

    $sub = sanitize_text_field((string) $t['sub']);
    $email = sanitize_email($t['email']);
    $found = get_users(['meta_key' => 'fpganow_google_sub', 'meta_value' => $sub, 'number' => 1]);
    $user = $found ? $found[0] : get_user_by('email', $email);
    if ($user && user_can($user, 'edit_posts')) {
        // never hand out a privileged session through this endpoint
        return new WP_Error('hwrun_google_staff', 'Editors and administrators sign in on the normal login page.', ['status' => 403]);
    }
    if (!$user) {
        $base = sanitize_user(strstr($email, '@', true), true);
        if ($base === '') { $base = 'user'; }
        $login = $base;
        for ($i = 2; username_exists($login); $i++) { $login = $base . $i; }
        $name = isset($t['name']) ? sanitize_text_field((string) $t['name']) : '';
        $id = wp_insert_user([
            'user_login' => $login, 'user_email' => $email, 'user_pass' => wp_generate_password(32, true, true),
            'display_name' => $name !== '' ? $name : $base, 'role' => 'subscriber',
        ]);
        if (is_wp_error($id)) { return new WP_Error('hwrun_google_create', 'Could not create the account.', ['status' => 500]); }
        $user = get_user_by('id', $id);
    }
    update_user_meta($user->ID, 'fpganow_google_sub', $sub);
    wp_set_current_user($user->ID);
    wp_set_auth_cookie($user->ID, true);
    return new WP_REST_Response(['ok' => true, 'name' => $user->display_name], 200);
}

add_action('rest_api_init', function () {
    register_rest_route(FPGANOW_HWRUN_NS, '/google-login', [
        'methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'fpganow_hwrun_google_login',
        'args' => ['credential' => ['required' => true]],
    ]);
    register_rest_route(FPGANOW_HWRUN_NS, '/catalog', [
        'methods' => 'GET', 'permission_callback' => '__return_true',
        'callback' => function () { return fpganow_hwrun_request('GET', '/api/catalog'); },
    ]);
    register_rest_route(FPGANOW_HWRUN_NS, '/runs', [
        'methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'fpganow_hwrun_start',
        'args' => ['pcap' => ['required' => true], 'implementation' => ['required' => true], 'board' => ['required' => true]],
    ]);
    register_rest_route(FPGANOW_HWRUN_NS, '/runs/(?P<id>[0-9a-f-]{1,40})', [
        'methods' => 'GET', 'permission_callback' => '__return_true',
        'callback' => function (WP_REST_Request $req) { return fpganow_hwrun_request('GET', '/api/runs/' . $req['id']); },
    ]);
    register_rest_route(FPGANOW_HWRUN_NS, '/runs/(?P<id>[0-9a-f-]{1,40})/csv', [
        'methods' => 'GET', 'permission_callback' => '__return_true',
        'callback' => function (WP_REST_Request $req) {
            $r = fpganow_hwrun_request('GET', '/api/runs/' . $req['id'] . '/csv', null, true);
            if (is_wp_error($r)) { return $r; }
            if ($r->get_status() !== 200) { return new WP_Error('hwrun_csv', 'CSV not available for this run', ['status' => $r->get_status()]); }
            // stream the file as-is instead of a JSON-encoded string
            nocache_headers();
            header('Content-Type: text/csv; charset=utf-8');
            header('Content-Disposition: attachment; filename="fpganow_hwrun_' . $req['id'] . '.csv"');
            echo $r->get_data(); // phpcs:ignore WordPress.Security.EscapeOutput -- CSV body from the service
            exit;
        },
    ]);
});

/* --------------------------------------------------------------- shortcode */
add_action('wp_enqueue_scripts', function () {
    $base = plugin_dir_url(__FILE__);
    wp_register_script('fpganow-hwrun-chartjs', $base . 'vendor/chart.umd.js', [], '4.4.1', true);
    wp_register_script('fpganow-hwrun', $base . 'assets/app.js', ['fpganow-hwrun-chartjs'], FPGANOW_HWRUN_VERSION, true);
    wp_register_style('fpganow-hwrun', $base . 'assets/app.css', [], FPGANOW_HWRUN_VERSION);
});

/** What the page script needs to know about sign-in. */
function fpganow_hwrun_auth_config() {
    $here = get_permalink();
    $u = wp_get_current_user();
    return [
        'required'       => fpganow_hwrun_require_login(),
        'loggedIn'       => is_user_logged_in(),
        'mayRun'         => fpganow_hwrun_user_may_run(),
        'user'           => is_user_logged_in() ? $u->display_name : '',
        'googleClientId' => fpganow_hwrun_google_client_id(),
        'emailAccounts'  => fpganow_hwrun_allow_email_accounts(),
        'loginUrl'       => wp_login_url($here),
        'registerUrl'    => get_option('users_can_register') ? wp_registration_url() : '',
        'logoutUrl'      => html_entity_decode(wp_logout_url($here)),
    ];
}

add_shortcode('fpganow_hwrun', function ($atts) {
    wp_enqueue_script('fpganow-hwrun');
    wp_enqueue_style('fpganow-hwrun');
    wp_localize_script('fpganow-hwrun', 'fpganowHwrun', [
        'restUrl' => esc_url_raw(rest_url(FPGANOW_HWRUN_NS . '/')),
        'nonce'   => wp_create_nonce('wp_rest'),
        'pollMs'  => 1500,
        'auth'    => fpganow_hwrun_auth_config(),
    ]);
    if (fpganow_hwrun_require_login() && !fpganow_hwrun_user_may_run() && fpganow_hwrun_google_client_id() !== '') {
        wp_enqueue_script('fpganow-hwrun-gsi', 'https://accounts.google.com/gsi/client', [], null, true); // phpcs:ignore -- Google's loader, unversioned by design
    }
    ob_start(); ?>
    <div class="fpganow-hwrun" id="fpganow-hwrun">
      <form class="hwrun-form" autocomplete="off">
        <div class="hwrun-field"><label for="hwrun-pcap">Test capture (pcap)</label>
          <select id="hwrun-pcap" name="pcap" required><option>loading...</option></select>
          <p class="hwrun-help" id="hwrun-pcap-help"></p></div>
        <div class="hwrun-field"><label for="hwrun-impl">Parser implementation</label>
          <select id="hwrun-impl" name="implementation" required></select>
          <p class="hwrun-help" id="hwrun-impl-help"></p></div>
        <div class="hwrun-field"><label for="hwrun-board">Board</label>
          <select id="hwrun-board" name="board" required></select>
          <p class="hwrun-help" id="hwrun-board-help"></p></div>
        <div class="hwrun-field" id="hwrun-speed-field" hidden><label for="hwrun-speed">Playback speed</label>
          <select id="hwrun-speed" name="speed"></select>
          <p class="hwrun-help" id="hwrun-speed-help"></p></div>
        <div class="hwrun-actions">
          <button type="submit" class="hwrun-run button" id="hwrun-run">Run on hardware</button>
          <span class="hwrun-status" id="hwrun-status"></span>
        </div>
        <div class="hwrun-auth" id="hwrun-auth" hidden></div>
      </form>
      <pre class="hwrun-log" id="hwrun-log" hidden></pre>
      <div class="hwrun-results" id="hwrun-results" hidden>
        <h3>Result</h3>
        <div class="hwrun-cards" id="hwrun-cards"></div>
        <div class="hwrun-toolbar">
          <a class="button" id="hwrun-csv" href="#" download>Download CSV</a>
          <button type="button" class="button" id="hwrun-report-toggle">Show scorer report</button>
          <label class="hwrun-metric">Chart: <select id="hwrun-metric">
            <option value="latency_ns">recv &rarr; parse latency per message (ns)</option>
            <option value="since_frame_start_ns">time since the frame's first message (ns)</option>
          </select></label>
        </div>
        <pre class="hwrun-report" id="hwrun-report" hidden></pre>
        <div class="hwrun-chart-wrap"><canvas id="hwrun-chart"></canvas></div>
        <h4>Per frame</h4>
        <div class="hwrun-table-wrap hwrun-frames"><table id="hwrun-frames"></table></div>
        <h4>Messages</h4>
        <div class="hwrun-table-wrap hwrun-messages"><table id="hwrun-table"></table></div>
      </div>
    </div>
    <?php return ob_get_clean();
});
