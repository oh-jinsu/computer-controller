// Test-only Sparkle host. Never compiled into Computer Controller.app.
// A unique fixture bundle + loopback feed prevent touching the installed app,
// its settings, browser or tunnel. All Sparkle signature checks stay enabled.
#import <Cocoa/Cocoa.h>
#import <Sparkle/Sparkle.h>

static void record(NSString *event, NSDictionary *fields) {
    NSString *path = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"MBSmokeEvidence"];
    NSMutableDictionary *row = [@{@"event": event, @"pid": @([[NSProcessInfo processInfo] processIdentifier]),
        @"version": [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleVersion"] ?: @"?"} mutableCopy];
    [row addEntriesFromDictionary:fields ?: @{}];
    NSData *json = [NSJSONSerialization dataWithJSONObject:row options:0 error:nil];
    NSMutableData *line = [json mutableCopy]; [line appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    if (![[NSFileManager defaultManager] fileExistsAtPath:path])
        [[NSFileManager defaultManager] createFileAtPath:path contents:nil attributes:@{NSFilePosixPermissions:@0600}];
    NSFileHandle *file = [NSFileHandle fileHandleForWritingAtPath:path];
    [file seekToEndOfFile]; [file writeData:line]; [file closeFile];
}

@interface SmokeDelegate : NSObject <NSApplicationDelegate, SPUUserDriver, SPUUpdaterDelegate>
@property(nonatomic, strong) SPUUpdater *updater;
@end
@implementation SmokeDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    record(@"launched", nil);
    NSBundle *bundle = [NSBundle mainBundle];
    if ([[bundle objectForInfoDictionaryKey:@"CFBundleVersion"] isEqual:@"2"]) {
        record(@"updated_app_relaunched", nil); [NSApp terminate:nil]; return;
    }
    self.updater = [[SPUUpdater alloc] initWithHostBundle:bundle applicationBundle:bundle userDriver:self delegate:self];
    NSError *error = nil;
    if (![self.updater startUpdater:&error]) {
        record(@"start_error", @{@"description":error.description ?: @"unknown"}); [NSApp terminate:nil]; return;
    }
    [self.updater checkForUpdates];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 120*NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        record(@"timeout", nil); [NSApp terminate:nil];
    });
}
- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest *)request reply:(void (^)(SUUpdatePermissionResponse *))reply {
    reply([[SUUpdatePermissionResponse alloc] initWithAutomaticUpdateChecks:NO sendSystemProfile:NO]);
}
- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation { record(@"check_started", nil); }
- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem *)item state:(SPUUserUpdateState *)state reply:(void (^)(SPUUserUpdateChoice))reply {
    record(@"update_found", @{@"target_version":item.versionString});
    if (item.informationOnlyUpdate || ![item.versionString isEqual:@"2"]) { reply(SPUUserUpdateChoiceDismiss); [NSApp terminate:nil]; return; }
    reply(SPUUserUpdateChoiceInstall);
}
- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData *)downloadData {}
- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError *)error {}
- (void)showUpdateNotFoundWithError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    record(@"not_found", @{@"description":error.description}); acknowledgement(); [NSApp terminate:nil];
}
- (void)showUpdaterError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    record(@"update_error", @{@"description":error.description}); acknowledgement(); [NSApp terminate:nil];
}
- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation { record(@"download_started", nil); }
- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)length {}
- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {}
- (void)showDownloadDidStartExtractingUpdate { record(@"download_finished", nil); }
- (void)showExtractionReceivedProgress:(double)progress {}
- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply { record(@"install_ready", nil); reply(SPUUserUpdateChoiceInstall); }
- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)terminated retryTerminatingApplication:(void (^)(void))retry { record(@"installing", nil); }
- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched acknowledgement:(void (^)(void))acknowledgement {
    record(@"installed_callback", @{@"relaunched":@(relaunched)}); acknowledgement();
}
- (void)dismissUpdateInstallation {}
- (void)updater:(SPUUpdater *)updater didAbortWithError:(NSError *)error {
    record(@"aborted", @{@"description":error.description}); [NSApp terminate:nil];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        SmokeDelegate *delegate = [[SmokeDelegate alloc] init];
        app.delegate = delegate; [app run];
    }
    return 0;
}
