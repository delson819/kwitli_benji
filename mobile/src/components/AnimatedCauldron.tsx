import { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";

import { useReducedMotion } from "../hooks/useReducedMotion";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";

const ORIGINAL_STAGE_SIZE = 154;
const STAGE_SIZE = 73;
const SCALE = STAGE_SIZE / ORIGINAL_STAGE_SIZE;

const scaled = (value: number) => value * SCALE;

type SteamPlumeProps = {
  delay: number;
  drift: number;
  duration: number;
  left: number;
  mirrored?: boolean;
  peakOpacity: number;
  reducedMotion: boolean;
  restingProgress: number;
  rise: number;
  size: number;
  texture: "base" | "wisp";
};

function SteamPlume({
  delay,
  drift,
  duration,
  left,
  mirrored = false,
  peakOpacity,
  reducedMotion,
  restingProgress,
  rise,
  size,
  texture,
}: SteamPlumeProps) {
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (reducedMotion) {
      progress.setValue(restingProgress);
      return undefined;
    }

    progress.setValue(0);

    const animation = Animated.sequence([
      Animated.delay(delay),
      Animated.loop(
        Animated.timing(progress, {
          duration,
          easing: Easing.linear,
          toValue: 1,
          isInteraction: false,
          useNativeDriver: true,
        }),
      ),
    ]);

    animation.start();

    return () => animation.stop();
  }, [delay, duration, progress, reducedMotion, restingProgress]);

  const direction = mirrored ? -1 : 1;

  const sourceBottom = texture === "base" ? 0.9 : 0.99;

  const plumeSize = scaled(size);
  const plumeRise = scaled(rise);
  const plumeDrift = scaled(drift);

  return (
    <Animated.Image
      blurRadius={texture === "base" ? 0.7 : 0.3}
      resizeMode="contain"
      source={
        texture === "base"
          ? require("../../assets/kwitli-steam-base.png")
          : require("../../assets/kwitli-steam-wisp.png")
      }
      style={[
        styles.steamPlume,
        {
          left: scaled(left),
          top: scaled(89) - plumeSize * sourceBottom,
          width: plumeSize,
          height: plumeSize,

          transformOrigin: `50% ${sourceBottom * 100}%`,

          opacity: progress.interpolate({
            inputRange: [0, 0.12, 0.35, 0.62, 0.84, 1],
            outputRange: [
              0,
              peakOpacity * 0.9,
              peakOpacity,
              peakOpacity * 0.76,
              peakOpacity * 0.28,
              0,
            ],
          }),

          transform: [
            {
              translateY: progress.interpolate({
                inputRange: [0, 0.3, 0.7, 1],
                outputRange: [
                  0,
                  plumeRise * -0.24,
                  plumeRise * -0.68,
                  -plumeRise,
                ],
              }),
            },
            {
              translateX: progress.interpolate({
                inputRange: [0, 0.25, 0.5, 0.75, 1],
                outputRange: [
                  0,
                  plumeDrift * -0.32,
                  plumeDrift * 0.4,
                  plumeDrift * 0.18,
                  plumeDrift,
                ],
              }),
            },
            {
              scaleX: progress.interpolate({
                inputRange: [0, 0.35, 0.7, 1],
                outputRange: [0.85, 1.01, 1.1, 1.2].map(
                  (scale) => scale * direction,
                ),
              }),
            },
            {
              scaleY: progress.interpolate({
                inputRange: [0, 0.3, 0.65, 1],
                outputRange: [0.85, 0.98, 1.06, 1.15],
              }),
            },
            {
              rotate: progress.interpolate({
                inputRange: [0, 0.35, 0.7, 1],
                outputRange:
                  drift > 0
                    ? ["-2deg", "2deg", "-1deg", "4deg"]
                    : ["2deg", "-2deg", "1deg", "-4deg"],
              }),
            },
          ],
        },
      ]}
    />
  );
}

type SteamBaseProps = Omit<SteamPlumeProps, "texture">;

function SteamBase(props: SteamBaseProps) {
  return <SteamPlume {...props} texture="base" />;
}

export function AnimatedCauldron() {
  const reducedMotion = useReducedMotion();
  const bob = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (reducedMotion) {
      bob.setValue(0);
      return undefined;
    }

    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(bob, {
          duration: 2200,
          easing: Easing.inOut(Easing.sin),
          toValue: 1,
          useNativeDriver: true,
        }),
        Animated.timing(bob, {
          duration: 2200,
          easing: Easing.inOut(Easing.sin),
          toValue: 0,
          useNativeDriver: true,
        }),
      ]),
    );

    animation.start();

    return () => animation.stop();
  }, [bob, reducedMotion]);

  return (
    <View
      accessible={false}
      importantForAccessibility="no-hide-descendants"
      style={styles.stage}
    >
      <Animated.View
        style={[
          styles.glow,
          {
            opacity: bob.interpolate({
              inputRange: [0, 1],
              outputRange: [0.1, 0.18],
            }),
            transform: [
              {
                scale: bob.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0.98, 1.03],
                }),
              },
            ],
          },
        ]}
      />

      <Animated.Image
        resizeMode="contain"
        source={require("../../assets/kwitli-cauldron-black.png")}
        style={[
          styles.image,
          {
            transform: [
              {
                translateY: bob.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0, scaled(-3)],
                }),
              },
              {
                rotate: bob.interpolate({
                  inputRange: [0, 1],
                  outputRange: ["-0.15deg", "0.15deg"],
                }),
              },
            ],
          },
        ]}
      />

      <Animated.View
        style={[
          styles.brothGlow,
          {
            opacity: bob.interpolate({
              inputRange: [0, 1],
              outputRange: [0.03, 0.09],
            }),
            transform: [
              {
                translateY: bob.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0, scaled(-3)],
                }),
              },
              {
                scaleX: bob.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0.96, 1.03],
                }),
              },
            ],
          },
        ]}
      />

      <View pointerEvents="none" style={styles.steamLayer}>
        <View style={styles.steamBackdrop} />

        {Array.from({ length: 12 }, (_, index) => (
          <View
            key={index}
            style={[
              styles.steamBlend,
              {
                top: scaled(44 + index * 2),
                opacity: 1 - (index + 1) / 13,
              },
            ]}
          />
        ))}

        <SteamBase
          delay={0}
          drift={5}
          duration={2600}
          left={29}
          peakOpacity={0.68}
          reducedMotion={reducedMotion}
          restingProgress={0.38}
          rise={42}
          size={96}
        />

        <SteamPlume
          delay={0}
          drift={-7}
          duration={1800}
          left={8}
          peakOpacity={0.86}
          reducedMotion={reducedMotion}
          restingProgress={0.3}
          rise={39}
          size={78}
          texture="wisp"
        />

        <SteamPlume
          delay={340}
          drift={6}
          duration={2300}
          left={25}
          mirrored
          peakOpacity={0.8}
          reducedMotion={reducedMotion}
          restingProgress={0.52}
          rise={45}
          size={82}
          texture="wisp"
        />

        <SteamPlume
          delay={720}
          drift={-5}
          duration={2760}
          left={43}
          peakOpacity={0.82}
          reducedMotion={reducedMotion}
          restingProgress={0.72}
          rise={43}
          size={86}
          texture="wisp"
        />

        <SteamPlume
          delay={1090}
          drift={7}
          duration={2080}
          left={61}
          mirrored
          peakOpacity={0.78}
          reducedMotion={reducedMotion}
          restingProgress={0.2}
          rise={40}
          size={74}
          texture="wisp"
        />

        <SteamPlume
          delay={1430}
          drift={-6}
          duration={3180}
          left={78}
          peakOpacity={0.76}
          reducedMotion={reducedMotion}
          restingProgress={0.6}
          rise={45}
          size={80}
          texture="wisp"
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    position: "relative",
    width: STAGE_SIZE,
    height: STAGE_SIZE,
    overflow: "visible",
    borderRadius: radius.lg,
    backgroundColor: colors.warmCream,
    shadowColor: colors.cornYellow,
    shadowOffset: {
      width: 0,
      height: scaled(5),
    },
    shadowOpacity: 0.2,
    shadowRadius: scaled(16),
    elevation: 1,
    marginVertical: -4,
  },

  glow: {
    position: "absolute",
    top: scaled(-6),
    right: scaled(-6),
    bottom: scaled(-6),
    left: scaled(-6),
    borderRadius: radius.xl,
    backgroundColor: colors.cornYellow,
    zIndex: 0,
  },

  image: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    width: "100%",
    height: "100%",
    borderRadius: radius.lg,
    zIndex: 1,
  },

  brothGlow: {
    position: "absolute",
    top: scaled(39),
    left: scaled(38),
    width: scaled(84),
    height: scaled(22),
    borderRadius: radius.pill,
    backgroundColor: colors.mangoOrange,
    zIndex: 2,
  },

  steamLayer: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 3,
  },

  steamBackdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: scaled(44),
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    backgroundColor: colors.warmCream,
  },

  steamBlend: {
    position: "absolute",
    left: 0,
    right: 0,
    height: scaled(2),
    backgroundColor: colors.warmCream,
  },

  steamPlume: {
    position: "absolute",
  },
});