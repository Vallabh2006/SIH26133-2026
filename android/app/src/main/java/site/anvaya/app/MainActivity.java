package site.anvaya.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.AlertDialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.KeyEvent;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebBackForwardList;
import android.webkit.WebChromeClient;
import android.webkit.WebHistoryItem;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {

    public static final String PREFS_NAME = "AnvayaPrefs";
    public static final String KEY_SERVER_URL = "server_url";
    public static final String DEFAULT_HTTP_URL = "https://app.anvaya.site/";
    public static final String CHANNEL_ID = "anvaya_notifications";
    public static final int NOTIFICATION_ID = 1001;
    public static final long CONNECTION_TIMEOUT_MS = 15000;

    private WebView webView;
    private ProgressBar progressBar;
    private SwipeRefreshLayout swipeRefreshLayout;
    private LinearLayout offlineLayout;
    private Button btnRetry;
    private Button btnChangeUrl;
    private SharedPreferences prefs;

    private final Handler timeoutHandler = new Handler(Looper.getMainLooper());
    private Runnable timeoutRunnable;
    private boolean pageLoadedSuccessfully = false;
    private long lastBackPressedTime = 0;

    private ValueCallback<Uri[]> filePathCallback;
    private String cameraPhotoPath;

    private GeolocationPermissions.Callback geolocationCallback;
    private String geolocationOrigin;

    private final ActivityResultLauncher<String[]> requestPermissionsLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestMultiplePermissions(), result -> {
                if (geolocationCallback != null && geolocationOrigin != null) {
                    boolean granted = Boolean.TRUE.equals(result.get(Manifest.permission.ACCESS_FINE_LOCATION))
                            || Boolean.TRUE.equals(result.get(Manifest.permission.ACCESS_COARSE_LOCATION));
                    geolocationCallback.invoke(geolocationOrigin, granted, false);
                    geolocationCallback = null;
                    geolocationOrigin = null;
                }
            });

    private final ActivityResultLauncher<Intent> fileChooserLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                if (filePathCallback == null) return;
                Uri[] results = null;
                if (result.getResultCode() == RESULT_OK) {
                    Intent data = result.getData();
                    if (data != null && data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    } else if (data != null && data.getClipData() != null) {
                        int count = data.getClipData().getItemCount();
                        results = new Uri[count];
                        for (int i = 0; i < count; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    } else if (cameraPhotoPath != null) {
                        results = new Uri[]{Uri.parse(cameraPhotoPath)};
                    }
                }
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);

        initViews();
        setupNotificationChannel();
        requestNotificationPermission();
        setupWebView();
        setupBackNavigation();

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            String initialUrl = prefs.getString(KEY_SERVER_URL, DEFAULT_HTTP_URL);
            loadUrlWithTimeout(initialUrl);
        }
    }

    private void initViews() {
        webView = findViewById(R.id.webView);
        progressBar = findViewById(R.id.progressBar);
        swipeRefreshLayout = findViewById(R.id.swipeRefreshLayout);
        offlineLayout = findViewById(R.id.offlineLayout);
        btnRetry = findViewById(R.id.btnRetry);
        btnChangeUrl = findViewById(R.id.btnChangeUrl);

        swipeRefreshLayout.setColorSchemeColors(ContextCompat.getColor(this, R.color.primary));
        swipeRefreshLayout.setOnRefreshListener(() -> {
            if (isNetworkAvailable()) {
                webView.reload();
            } else {
                swipeRefreshLayout.setRefreshing(false);
                Toast.makeText(this, "No internet connection", Toast.LENGTH_SHORT).show();
            }
        });

        btnRetry.setOnClickListener(v -> {
            String url = prefs.getString(KEY_SERVER_URL, DEFAULT_HTTP_URL);
            hideOffline();
            loadUrlWithTimeout(url);
        });

        btnChangeUrl.setOnClickListener(v -> showServerUrlDialog());
    }

    private void setupNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            CharSequence name = "Anvaya Vistara Notifications";
            String description = "Alerts, teleconsult updates, and reminders";
            int importance = NotificationManager.IMPORTANCE_HIGH;
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, name, importance);
            channel.setDescription(description);
            channel.enableVibration(true);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissionsLauncher.launch(new String[]{Manifest.permission.POST_NOTIFICATIONS});
            }
        }
    }

    private void showServerUrlDialog() {
        String currentUrl = prefs.getString(KEY_SERVER_URL, DEFAULT_HTTP_URL);
        EditText input = new EditText(this);
        input.setText(currentUrl);
        input.setSingleLine(true);
        input.setPadding(48, 32, 48, 32);

        new AlertDialog.Builder(this)
                .setTitle("Configure Server Endpoint")
                .setMessage("Enter the healthcare portal URL:")
                .setView(input)
                .setPositiveButton("Connect", (dialog, which) -> {
                    String newUrl = input.getText().toString().trim();
                    if (!newUrl.isEmpty()) {
                        if (!newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
                            newUrl = "https://" + newUrl;
                        }
                        prefs.edit().putString(KEY_SERVER_URL, newUrl).apply();
                        hideOffline();
                        loadUrlWithTimeout(newUrl);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void loadUrlWithTimeout(String url) {
        cancelTimeout();
        pageLoadedSuccessfully = false;
        progressBar.setVisibility(View.VISIBLE);

        if (!isNetworkAvailable()) {
            showOffline();
            return;
        }

        timeoutRunnable = () -> {
            if (!pageLoadedSuccessfully) {
                webView.stopLoading();
                showOffline();
            }
        };
        timeoutHandler.postDelayed(timeoutRunnable, CONNECTION_TIMEOUT_MS);

        webView.loadUrl(url);
    }

    private void cancelTimeout() {
        if (timeoutRunnable != null) {
            timeoutHandler.removeCallbacks(timeoutRunnable);
            timeoutRunnable = null;
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setSupportMultipleWindows(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);

        String defaultUa = settings.getUserAgentString();
        settings.setUserAgentString(defaultUa + " AnvayaVistaraApp/1.1");

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            cookieManager.setAcceptThirdPartyCookies(webView, true);
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        if (isNetworkAvailable()) {
            settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        } else {
            settings.setCacheMode(WebSettings.LOAD_CACHE_ELSE_NETWORK);
        }

        webView.addJavascriptInterface(new AndroidBridge(this), "AndroidBridge");
        webView.addJavascriptInterface(new AndroidBridge(this), "Android");

        webView.setWebViewClient(new CustomWebViewClient());
        webView.setWebChromeClient(new CustomWebChromeClient());
    }

    private void setupBackNavigation() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                navigateBackOrExit();
            }
        });
    }

    private void navigateBackOrExit() {
        if (webView.canGoBack()) {
            WebBackForwardList history = webView.copyBackForwardList();
            int currentIndex = history.getCurrentIndex();
            
            if (currentIndex > 0) {
                WebHistoryItem currentItem = history.getItemAtIndex(currentIndex);
                WebHistoryItem prevItem = history.getItemAtIndex(currentIndex - 1);
                
                String currentUrl = currentItem != null ? currentItem.getUrl() : "";
                String prevUrl = prevItem != null ? prevItem.getUrl() : "";
                
                // If previous page is login/redirect and user is on target page, jump 2 back
                if (currentUrl.contains("/admin/@") || currentUrl.contains("/patient/@") || currentUrl.contains("/phc/@")) {
                    if (prevUrl.endsWith("/login") || prevUrl.endsWith("/app") || prevUrl.contains("/auth/")) {
                        if (currentIndex > 1) {
                            webView.goBackOrForward(-2);
                            return;
                        }
                    }
                }
            }
            webView.goBack();
        } else {
            long now = System.currentTimeMillis();
            if (now - lastBackPressedTime < 2000) {
                finish();
            } else {
                lastBackPressedTime = now;
                Toast.makeText(MainActivity.this, "Press back again to exit", Toast.LENGTH_SHORT).show();
            }
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            navigateBackOrExit();
            return true;
        } else if (keyCode == KeyEvent.KEYCODE_FORWARD) {
            if (webView.canGoForward()) {
                webView.goForward();
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }

    private void showOffline() {
        progressBar.setVisibility(View.GONE);
        swipeRefreshLayout.setRefreshing(false);
        webView.setVisibility(View.GONE);
        offlineLayout.setVisibility(View.VISIBLE);
    }

    private void hideOffline() {
        offlineLayout.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
    }

    private boolean isNetworkAvailable() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                NetworkCapabilities nc = cm.getNetworkCapabilities(cm.getActiveNetwork());
                return nc != null && (nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                        nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                        nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET));
            } else {
                return cm.getActiveNetworkInfo() != null && cm.getActiveNetworkInfo().isConnected();
            }
        }
        return false;
    }

    private File createImageFile() throws IOException {
        String timeStamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(new Date());
        String imageFileName = "JPEG_" + timeStamp + "_";
        File storageDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES);
        return File.createTempFile(imageFileName, ".jpg", storageDir);
    }

    public class AndroidBridge {
        private final Context context;

        public AndroidBridge(Context context) {
            this.context = context;
        }

        @JavascriptInterface
        public void showToast(String message) {
            if (message != null && !message.isEmpty()) {
                runOnUiThread(() -> Toast.makeText(context, message, Toast.LENGTH_SHORT).show());
            }
        }

        @JavascriptInterface
        public void showNotification(String title, String message, String targetUrl) {
            runOnUiThread(() -> {
                NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
                if (nm == null) return;

                Intent intent = new Intent(context, MainActivity.class);
                if (targetUrl != null && !targetUrl.isEmpty()) {
                    intent.setData(Uri.parse(targetUrl));
                }
                intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);

                PendingIntent pendingIntent = PendingIntent.getActivity(
                        context,
                        (int) System.currentTimeMillis(),
                        intent,
                        Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT : PendingIntent.FLAG_UPDATE_CURRENT
                );

                NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                        .setSmallIcon(R.mipmap.ic_launcher)
                        .setContentTitle(title != null ? title : "Anvaya Vistara")
                        .setContentText(message != null ? message : "")
                        .setStyle(new NotificationCompat.BigTextStyle().bigText(message != null ? message : ""))
                        .setPriority(NotificationCompat.PRIORITY_HIGH)
                        .setAutoCancel(true)
                        .setContentIntent(pendingIntent);

                nm.notify((int) System.currentTimeMillis(), builder.build());
            });
        }

        @JavascriptInterface
        public void navigateBack() {
            runOnUiThread(MainActivity.this::navigateBackOrExit);
        }

        @JavascriptInterface
        public void navigateForward() {
            runOnUiThread(() -> {
                if (webView.canGoForward()) {
                    webView.goForward();
                }
            });
        }

        @JavascriptInterface
        public boolean canGoBack() {
            return webView.canGoBack();
        }

        @JavascriptInterface
        public boolean canGoForward() {
            return webView.canGoForward();
        }
    }

    private class CustomWebViewClient extends WebViewClient {
        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            progressBar.setVisibility(View.VISIBLE);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            progressBar.setVisibility(View.GONE);
            swipeRefreshLayout.setRefreshing(false);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                CookieManager.getInstance().flush();
            }
            if (!url.startsWith("data:") && !url.equals("about:blank")) {
                pageLoadedSuccessfully = true;
                cancelTimeout();
                hideOffline();
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                pageLoadedSuccessfully = false;
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            if (url.startsWith("tel:") || url.startsWith("mailto:") || url.startsWith("sms:") || url.startsWith("whatsapp:")) {
                try {
                    Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    startActivity(intent);
                    return true;
                } catch (Exception e) {
                    return false;
                }
            }
            return false;
        }
    }

    private class CustomWebChromeClient extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            progressBar.setProgress(newProgress);
            if (newProgress == 100) {
                progressBar.setVisibility(View.GONE);
            }
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.ACCESS_FINE_LOCATION)
                    != PackageManager.PERMISSION_GRANTED) {
                geolocationCallback = callback;
                geolocationOrigin = origin;
                requestPermissionsLauncher.launch(new String[]{
                        Manifest.permission.ACCESS_FINE_LOCATION,
                        Manifest.permission.ACCESS_COARSE_LOCATION
                });
            } else {
                callback.invoke(origin, true, false);
            }
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            request.grant(request.getResources());
        }

        @Override
        public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
            if (MainActivity.this.filePathCallback != null) {
                MainActivity.this.filePathCallback.onReceiveValue(null);
            }
            MainActivity.this.filePathCallback = filePathCallback;

            Intent takePictureIntent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            if (takePictureIntent.resolveActivity(getPackageManager()) != null) {
                File photoFile = null;
                try {
                    photoFile = createImageFile();
                    takePictureIntent.putExtra("PhotoPath", cameraPhotoPath);
                } catch (IOException ex) {
                }
                if (photoFile != null) {
                    cameraPhotoPath = "file:" + photoFile.getAbsolutePath();
                    Uri photoURI = FileProvider.getUriForFile(
                            MainActivity.this,
                            getApplicationContext().getPackageName() + ".fileprovider",
                            photoFile
                    );
                    takePictureIntent.putExtra(MediaStore.EXTRA_OUTPUT, photoURI);
                } else {
                    takePictureIntent = null;
                }
            }

            Intent contentSelectionIntent = new Intent(Intent.ACTION_GET_CONTENT);
            contentSelectionIntent.addCategory(Intent.CATEGORY_OPENABLE);
            contentSelectionIntent.setType("*/*");
            if (fileChooserParams.getAcceptTypes() != null && fileChooserParams.getAcceptTypes().length > 0) {
                contentSelectionIntent.putExtra(Intent.EXTRA_MIME_TYPES, fileChooserParams.getAcceptTypes());
            }

            Intent[] intentArray;
            if (takePictureIntent != null) {
                intentArray = new Intent[]{takePictureIntent};
            } else {
                intentArray = new Intent[0];
            }

            Intent chooserIntent = new Intent(Intent.ACTION_CHOOSER);
            chooserIntent.putExtra(Intent.EXTRA_INTENT, contentSelectionIntent);
            chooserIntent.putExtra(Intent.EXTRA_TITLE, "Select Document or Image");
            chooserIntent.putExtra(Intent.EXTRA_INITIAL_INTENTS, intentArray);

            fileChooserLauncher.launch(chooserIntent);
            return true;
        }
    }

    @Override
    protected void onDestroy() {
        cancelTimeout();
        super.onDestroy();
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }
}
