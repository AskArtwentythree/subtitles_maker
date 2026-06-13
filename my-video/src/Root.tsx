import "./index.css";
import { Composition } from "remotion";
import { AutoEdit, totalFrames, type Edl, type StyleId } from "./AutoEdit";
import edlJson from "./edl.json";

const defaultEdl: Edl = { ...(edlJson as unknown as Edl), videoFile: "video1.mov" };

const calcMeta = ({ props }: { props: { edl: Edl; styleId?: StyleId } }) => {
  const edl = props.edl;
  const fps = edl.meta?.fps || 30;
  // Рендерим в стандартном вертикальном 1080x1920 (как в HyperFrames), а исходник
  // масштабируем object-fit: cover. Так размеры подписей/плашек (заданные в px под
  // 1080) выглядят правильно и держатся в нижней трети, а не «распухают» на узком
  // холсте источника.
  return {
    durationInFrames: totalFrames(edl, fps),
    fps,
    width: 1080,
    height: 1920,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="AutoEdit"
        component={AutoEdit}
        defaultProps={{ edl: defaultEdl, styleId: "a" as StyleId }}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="AutoEditB"
        component={AutoEdit}
        defaultProps={{ edl: defaultEdl, styleId: "b" as StyleId }}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={calcMeta}
      />
    </>
  );
};
