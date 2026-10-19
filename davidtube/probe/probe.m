// Renders one rendition of an Assets.car with the system CoreUI and prints what
// it draws.  Usage: probe CAR NAME   (private API; for diagnostics only)
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>

@interface CUINamedImage : NSObject
@property (readonly) CGImageRef image;
@property (readonly) double scale;
@end
@interface CUICatalog : NSObject
- (instancetype)initWithURL:(NSURL *)url error:(NSError **)error;
- (NSArray *)imagesWithName:(NSString *)name;
@end

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc < 3) { printf("usage: probe CAR NAME\n"); return 0; }
        dlopen("/System/Library/PrivateFrameworks/CoreUI.framework/CoreUI", RTLD_NOW);
        Class cls = NSClassFromString(@"CUICatalog");
        if (!cls) { printf("  CoreUI not available\n"); return 0; }
        NSError *err = nil;
        id cat = [[cls alloc] initWithURL:[NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]] error:&err];
        if (!cat) { printf("  cannot open catalog: %s\n", err.description.UTF8String); return 0; }
        NSArray *imgs = [cat imagesWithName:[NSString stringWithUTF8String:argv[2]]];
        if (imgs.count == 0) { printf("  no images named %s\n", argv[2]); return 0; }
        for (CUINamedImage *ni in imgs) {
            CGImageRef im = ni.image;
            if (!im) { printf("  @%.0fx: NO IMAGE (decode failed)\n", ni.scale); continue; }
            size_t w = CGImageGetWidth(im), h = CGImageGetHeight(im);
            CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
            uint8_t *px = calloc(w * h, 4);
            CGContextRef ctx = CGBitmapContextCreate(px, w, h, 8, w * 4, cs,
                kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
            CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), im);
            size_t transparent = 0, opaque = 0, white = 0;
            for (size_t i = 0; i < w * h; i++) {
                uint8_t *p = px + i * 4;
                if (p[3] == 0) transparent++;
                else if (p[3] == 255) opaque++;
                if (p[3] > 200 && p[0] > 200 && p[1] > 200 && p[2] > 200) white++;
            }
            printf("  @%.0fx %zux%zu alphaInfo=%u: transparent=%.0f%% opaque=%.0f%% whitePixels=%.1f%% corner=%02x%02x%02x%02x\n",
                   ni.scale, w, h, (unsigned)CGImageGetAlphaInfo(im),
                   100.0 * transparent / (w * h), 100.0 * opaque / (w * h), 100.0 * white / (w * h),
                   px[0], px[1], px[2], px[3]);
            CGContextRelease(ctx); CGColorSpaceRelease(cs); free(px);
        }
    }
    return 0;
}
