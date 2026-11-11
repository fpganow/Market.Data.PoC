<?php
/**
 * Plugin Name: FPGA Now - Run on Hardware
 * Description: Replays one of the pre-canned CBOE PITCH test pcaps against the live FPGA board (LabVIEW FPGA or Verilog parser) through the hwrun service and shows every parsed message with its latency: table, CSV download and chart. Shortcode: [fpganow_hwrun]
 * Version: 1.1.0
 * Author: FPGA Now
 * License: GPL-2.0-or-later
 *
 * The page talks only to this site's REST API (fpganow-hwrun/v1/...); the plugin forwards the
 * calls server-side to the run service (Market.Data.PoC/tools/hwrun/hwrun_server.py) with a
 * bearer token, so the service and its token are never exposed to the browser. Settings ->
 * Run on Hardware holds the service URL, the token and the per-visitor cooldown; the constants
 * FPGANOW_HWRUN_URL / FPGANOW_HWRUN_TOKEN in wp-config.php override them.
 */
if (!defined('ABSPATH')) { exit; }

define('FPGANOW_HWRUN_VERSION', '1.1.0');
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

/* ---------------------------------------------------------------- settings */
add_action('admin_menu', function () {
    add_options_page('Run on Hardware', 'Run on Hardware', 'manage_options', 'fpganow-hwrun', 'fpganow_hwrun_settings_page');
});
add_action('admin_init', function () {
    register_setting('fpganow_hwrun', 'fpganow_hwrun_url', ['sanitize_callback' => 'esc_url_raw']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_token', ['sanitize_callback' => 'sanitize_text_field']);
    register_setting('fpganow_hwrun', 'fpganow_hwrun_cooldown', ['sanitize_callback' => 'absint']);
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
                  <p class="description">Minimum time between two runs started from the same IP address.</p></td></tr>
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
    $key = 'fpganow_hwrun_rl_' . md5(fpganow_hwrun_client_ip());
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

add_action('rest_api_init', function () {
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

add_shortcode('fpganow_hwrun', function ($atts) {
    wp_enqueue_script('fpganow-hwrun');
    wp_enqueue_style('fpganow-hwrun');
    wp_localize_script('fpganow-hwrun', 'fpganowHwrun', [
        'restUrl' => esc_url_raw(rest_url(FPGANOW_HWRUN_NS . '/')),
        'nonce'   => wp_create_nonce('wp_rest'),
        'pollMs'  => 1500,
    ]);
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
